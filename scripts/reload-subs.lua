-- reload-subtitles.lua
--
-- Features:
-- - U: Manually reload all external subtitle tracks
-- - Alt+R: Toggle automatic subtitle reload (checks for changes every 2 seconds)
-- - Ctrl+U: Force reload subtitles and rescan directory
-- - Auto-switches from .unfinished.srt to .srt when transcription completes
--
-- Save this file to ~/.config/mpv/scripts/

-- Configuration
local auto_reload_interval = 2  -- Check for subtitle changes every 2 seconds
local supported_sub_exts = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx", ".sup"}
local debug_mode = false  -- Set to true for verbose logging

-- State variables
local auto_reload_enabled = true  -- ON by default: required for .unfinished.srt auto-switch
local auto_reload_timer = nil
local subtitle_files = {}
local subtitle_mtimes = {}
local last_video_path = nil
local using_unfinished = false  -- Track if we're using .unfinished.srt
local final_srt_path = nil  -- Store path to final .srt
local unfinished_symlinks = {}  -- final_path -> .unfinished.srt target (symlink mode)

-- Utility functions
local utils = require 'mp.utils'

local function log(level, message)
    if level == "debug" and not debug_mode then return end
    mp.msg[level](message)
end

local function get_file_info(file_path)
    if not file_path or file_path == "" then
        return nil
    end
    
    local info = utils.file_info(file_path)
    return info
end

local function get_mtime(file_path)
    local info = get_file_info(file_path)
    return info and info.mtime or nil
end

local function file_exists(file_path)
    local info = get_file_info(file_path)
    return info ~= nil
end

-- Resolve a symlink's target. Returns nil if path is not a symlink.
local function read_symlink(file_path)
    local escaped = file_path:gsub('"', '\\"')
    local p = io.popen('readlink "' .. escaped .. '" 2>/dev/null')
    if not p then return nil end
    local target = p:read("*l")
    p:close()
    if not target or target == "" then return nil end
    -- Resolve relative targets against the symlink's directory
    if not target:match("^/") then
        local dir = utils.split_path(file_path)
        target = utils.join_path(dir, target)
    end
    return target
end

-- If file_path is a symlink pointing to a .unfinished.srt, return the
-- absolute target path; otherwise return nil.
local function unfinished_symlink_target(file_path)
    local target = read_symlink(file_path)
    if target and target:match("%.unfinished%.srt$") then
        return target
    end
    return nil
end

local function get_video_dir()
    local video_path = mp.get_property("path")
    if not video_path then return nil end
    
    local dir = utils.split_path(video_path)
    return dir
end

local function get_video_basename()
    local video_path = mp.get_property("path")
    if not video_path then return nil end
    
    local _, filename = utils.split_path(video_path)
    local basename = filename:match("(.+)%..+$") or filename
    return basename
end

local function has_supported_extension(filename)
    local ext = filename:match("%.([^%.]+)$")
    if not ext then return false end
    
    ext = "." .. ext:lower()
    for _, supported_ext in ipairs(supported_sub_exts) do
        if ext == supported_ext then
            return true
        end
    end
    return false
end

-- Check if transcribe.py is running via symlink mode:
-- during transcription, final.srt is a symlink to final.unfinished.srt.
-- On completion, os.rename() replaces the symlink with a real file.
local function check_unfinished_symlinks()
    for final_path, _ in pairs(unfinished_symlinks) do
        -- Transcription done when final path is no longer a symlink
        if not read_symlink(final_path) and file_exists(final_path) then
            log("info", "Transcription complete (symlink replaced): " .. final_path)
            return final_path
        end
    end
    return nil
end

-- NEW: Check if transcription is complete
local function check_transcription_complete()
    if not using_unfinished or not final_srt_path then
        return false
    end
    
    -- Check if final .srt exists and is newer/larger than .unfinished.srt
    if file_exists(final_srt_path) then
        local final_info = get_file_info(final_srt_path)
        
        -- Find the .unfinished.srt in our tracked files
        local unfinished_path = nil
        for _, path in ipairs(subtitle_files) do
            if path:match("%.unfinished%.srt$") then
                unfinished_path = path
                break
            end
        end
        
        if unfinished_path then
            local unfinished_info = get_file_info(unfinished_path)
            
            -- If final file exists and is different size, transcription is done
            if final_info and unfinished_info then
                if final_info.size > 0 and final_info.size ~= unfinished_info.size then
                    log("info", "Transcription complete! Switching to final .srt")
                    return true
                end
            end
        end
    end
    
    return false
end

local get_external_subtitle_tracks  -- defined below; used by switch_to_final_srt

-- Switch from .unfinished.srt (or a symlinked final .srt) to the final file
local function switch_to_final_srt(final_path)
    final_srt_path = final_path or final_srt_path
    if not final_srt_path or not file_exists(final_srt_path) then
        return
    end

    log("info", "Switching to final subtitle: " .. final_srt_path)
    
    -- Remove all current subtitle tracks
    local external_subs = get_external_subtitle_tracks()
    for _, sub in ipairs(external_subs) do
        mp.command("sub-remove " .. sub.id)
    end
    
    -- Add the final .srt
    local escaped_path = final_srt_path:gsub('"', '\\"')
    mp.command('sub-add "' .. escaped_path .. '"')
    
    -- Update tracking
    subtitle_files = {final_srt_path}
    subtitle_mtimes = {[final_srt_path] = get_mtime(final_srt_path)}
    unfinished_symlinks[final_srt_path] = nil
    using_unfinished = false
    
    mp.osd_message("Switched to final subtitle", 3)
end

-- Extract --sub-file arguments from mpv's own command line. Needed for URL
-- playback where the subtitle path is not derivable from the video path,
-- and works even if the file did not exist when mpv started.
local function sub_files_from_cmdline()
    local paths = {}
    local f = io.open("/proc/self/cmdline", "r")
    if not f then return paths end
    local data = f:read("*a") or ""
    f:close()

    for arg in data:gmatch("[^%z]+") do
        local path = arg:match("^%-%-sub%-file=(.+)$")
        if path then
            table.insert(paths, path)
        end
    end

    return paths
end

-- Function to find subtitle files in video directory.
-- loaded_subs: external sub tracks captured before they were removed, needed
-- for URL playback where the subtitle path cannot be derived from the video.
local function find_subtitle_files(loaded_subs)
    local video_path = mp.get_property("path")
    
    if not video_path then
        return {}
    end
    
    local is_url = video_path:match("^https?://") or video_path:match("^ytdl://")
    
    -- For URLs there is no local video file, so the video base name cannot
    -- be derived. Only the subtitles mpv already loaded (e.g. via
    -- --sub-file) are relevant: loading every .srt in the folder would add
    -- dozens of unrelated tracks.
    if is_url then
        local loaded = {}
        local source = loaded_subs or get_external_subtitle_tracks()
        for _, sub in ipairs(source) do
            local filename = type(sub) == "table" and sub.filename or sub
            if filename then
                table.insert(loaded, filename)
            end
        end

        -- Also honour --sub-file paths, including files mpv failed to open
        -- at startup (transcription may not have started yet)
        for _, path in ipairs(sub_files_from_cmdline()) do
            local found = false
            for _, existing in ipairs(loaded) do
                if existing == path then
                    found = true
                    break
                end
            end
            if not found and file_exists(path) then
                table.insert(loaded, path)
            end
        end
        log("debug", "Video is a URL, tracking subtitles: " .. #loaded)

        for _, path in ipairs(loaded) do
            local target = unfinished_symlink_target(path)
            if target then
                unfinished_symlinks[path] = target
                log("info", "Tracking unfinished symlink: " .. path)
            elseif path:match("%.unfinished%.srt$") then
                using_unfinished = true
                final_srt_path = path:gsub("%.unfinished%.srt$", ".srt")
                log("info", "Tracking unfinished subtitle: " .. path)
            end
        end

        return loaded
    end

    local video_dir = utils.split_path(video_path)
    
    if not video_dir then
        return {}
    end
    
    local files = utils.readdir(video_dir)
    if not files then
        log("warn", "Could not read directory: " .. video_dir)
        return {}
    end
    
    local subtitle_candidates = {}
    local found_unfinished = false
    
    for _, file in ipairs(files) do
        if has_supported_extension(file) then
            local full_path = utils.join_path(video_dir, file)

            -- Detect symlink mode: .srt that is a symlink to .unfinished.srt
            local sym_target = unfinished_symlink_target(full_path)
            if sym_target then
                unfinished_symlinks[full_path] = sym_target
                log("debug", "Found unfinished symlink: " .. full_path .. " -> " .. sym_target)
            end

            -- Local files: only include if basename matches the video
            local should_include = false
            local video_basename = get_video_basename()
            if video_basename then
                local sub_basename = file:match("(.+)%..+$") or file
                should_include = sub_basename:find(video_basename, 1, true) == 1
            end
            
            if should_include then
                -- Check if this is an .unfinished.srt file
                if file:match("%.unfinished%.srt$") then
                    found_unfinished = true
                    using_unfinished = true
                    
                    -- Derive the final .srt path
                    final_srt_path = full_path:gsub("%.unfinished%.srt$", ".srt")
                    log("debug", "Found unfinished subtitle: " .. full_path)
                    log("debug", "Will watch for final: " .. final_srt_path)
                    
                    -- Prefer .unfinished.srt if final doesn't exist yet
                    if not file_exists(final_srt_path) then
                        table.insert(subtitle_candidates, full_path)
                    else
                        -- Final exists, use it instead
                        table.insert(subtitle_candidates, final_srt_path)
                        using_unfinished = false
                    end
                elseif not file:match("%.unfinished%.") then
                    -- Regular subtitle file (not .unfinished)
                    table.insert(subtitle_candidates, full_path)
                end
                
                log("debug", "Found subtitle candidate: " .. full_path)
            end
        end
    end
    
    return subtitle_candidates
end
-- Function to get currently loaded external subtitle tracks
get_external_subtitle_tracks = function()
    local tracks = mp.get_property_native("track-list") or {}
    local external_subs = {}
    
    for _, track in ipairs(tracks) do
        if track.type == "sub" and track.external == true then
            if track.external_filename and track.external_filename ~= "" then
                table.insert(external_subs, {
                    id = track.id,
                    filename = track.external_filename,
                    selected = track.selected
                })
                log("debug", "Found external sub track: " .. track.external_filename .. " (ID: " .. track.id .. ")")
            end
        end
    end
    
    return external_subs
end

-- Function to reload all subtitle tracks
local function reload_all_subs(quiet, force_rescan)
    local external_subs = get_external_subtitle_tracks()
    local selected_track_filename = nil
    local count = 0

    -- If we have no tracked files yet, adopt the subs mpv already loaded
    -- (e.g. via --sub-file) so a manual reload doesn't remove everything
    if #subtitle_files == 0 and not force_rescan then
        for _, sub in ipairs(external_subs) do
            table.insert(subtitle_files, sub.filename)
            subtitle_mtimes[sub.filename] = get_mtime(sub.filename)
        end
    end

    -- Remember which track was selected
    for _, sub in ipairs(external_subs) do
        if sub.selected then
            selected_track_filename = sub.filename
            break
        end
    end
    
    -- Remove all external subtitle tracks
    for _, sub in ipairs(external_subs) do
        mp.command("sub-remove " .. sub.id)
        log("debug", "Removed subtitle track: " .. sub.filename)
    end
    
    local subtitle_candidates = {}
    
    if force_rescan then
        -- Find subtitle files. Pass the tracks captured before removal, since
        -- URL mode relies on them and they are gone from the track list now.
        subtitle_candidates = find_subtitle_files(external_subs)
    else
        -- Use existing tracked files
        for _, filename in ipairs(subtitle_files) do
            if file_exists(filename) then
                table.insert(subtitle_candidates, filename)
            end
        end
    end
    
    -- Reset tracking arrays
    subtitle_files = {}
    subtitle_mtimes = {}
    
    -- Add subtitle files
    for _, sub_path in ipairs(subtitle_candidates) do
        local escaped_path = sub_path:gsub('"', '\\"')
        mp.command('sub-add "' .. escaped_path .. '"')
        
        -- Store for tracking
        table.insert(subtitle_files, sub_path)
        subtitle_mtimes[sub_path] = get_mtime(sub_path)
        count = count + 1
        
        log("debug", "Added subtitle track: " .. sub_path)
    end
    
    -- Try to restore selected track
    if selected_track_filename then
        mp.add_timeout(0.1, function()
            local new_tracks = get_external_subtitle_tracks()
            for _, track in ipairs(new_tracks) do
                if track.filename == selected_track_filename then
                    mp.set_property("sid", track.id)
                    log("debug", "Restored selected subtitle track: " .. selected_track_filename)
                    break
                end
            end
        end)
    end
    
    -- Display message
    if not quiet then
        if count > 0 then
            mp.osd_message("Reloaded " .. count .. " subtitle track(s)", 3)
            log("info", "Reloaded " .. count .. " subtitle track(s)")
        else
            mp.osd_message("No subtitle tracks found", 3)
            log("info", "No subtitle tracks found")
        end
    end
    
    return count
end

-- Function to check for subtitle file changes
local function check_subtitle_changes()
    -- Check symlink-mode transcription completion (final.srt symlinked
    -- to .unfinished.srt during transcription, replaced by os.rename)
    local done_path = check_unfinished_symlinks()
    if done_path then
        switch_to_final_srt(done_path)
        return
    end

    -- NEW: Check if transcription completed
    if using_unfinished and check_transcription_complete() then
        switch_to_final_srt()
        return
    end

    -- Lazily detect symlinks on tracked files (in case the initial scan
    -- ran before the symlink was created)
    for _, file_path in ipairs(subtitle_files) do
        if not unfinished_symlinks[file_path] then
            local target = unfinished_symlink_target(file_path)
            if target then
                unfinished_symlinks[file_path] = target
                log("info", "Now tracking unfinished symlink: " .. file_path)
            end
        end
    end
    
    local changes_detected = false
    local changed_files = {}
    
    for _, file_path in ipairs(subtitle_files) do
        local current_mtime = get_mtime(file_path)

        -- If file is a symlink to a growing .unfinished.srt, the target's
        -- mtime is the one that changes; include it in change detection
        local sym_target = unfinished_symlinks[file_path]
        if sym_target then
            local target_mtime = get_mtime(sym_target)
            if target_mtime and (not current_mtime or target_mtime > current_mtime) then
                current_mtime = target_mtime
            end
        end

        local stored_mtime = subtitle_mtimes[file_path]

        if not current_mtime then
            -- File was deleted
            log("info", "Subtitle file deleted: " .. file_path)
            changes_detected = true
            table.insert(changed_files, file_path .. " (deleted)")
        elseif not stored_mtime or current_mtime > stored_mtime then
            -- File was modified
            log("info", "Subtitle file modified: " .. file_path)
            changes_detected = true
            table.insert(changed_files, file_path)
        end
    end
    
    -- Also check for new subtitle files
    local video_path = mp.get_property("path")
    if video_path ~= last_video_path then
        changes_detected = true
        last_video_path = video_path
        log("info", "Video file changed, rescanning subtitles")
    end
    
    if changes_detected then
        reload_all_subs(true, false)
        local message = "Auto-reloaded subtitles"
        if #changed_files > 0 then
            message = message .. " (" .. #changed_files .. " changed)"
        end
        mp.osd_message(message, 2)
    end
end

-- Function to toggle auto-reload
local function toggle_auto_reload()
    auto_reload_enabled = not auto_reload_enabled
    
    if auto_reload_enabled then
        -- Initialize tracking
        reload_all_subs(true, true)
        
        -- Start timer
        if auto_reload_timer then
            auto_reload_timer:kill()
        end
        auto_reload_timer = mp.add_periodic_timer(auto_reload_interval, check_subtitle_changes)
        
        mp.osd_message("Auto subtitle reload: ON", 3)
        log("info", "Auto subtitle reload enabled")
    else
        -- Stop timer
        if auto_reload_timer then
            auto_reload_timer:kill()
            auto_reload_timer = nil
        end
        
        mp.osd_message("Auto subtitle reload: OFF", 3)
        log("info", "Auto subtitle reload disabled")
    end
end

-- Event handlers
mp.register_event("file-loaded", function()
    log("debug", "File loaded event triggered")
    last_video_path = mp.get_property("path")

    -- Reset state
    using_unfinished = false
    final_srt_path = nil
    unfinished_symlinks = {}

    -- Adopt subs mpv already loaded (e.g. via --sub-file) so tracking
    -- works even before the first periodic scan
    subtitle_files = {}
    subtitle_mtimes = {}
    for _, sub in ipairs(get_external_subtitle_tracks()) do
        table.insert(subtitle_files, sub.filename)
        subtitle_mtimes[sub.filename] = get_mtime(sub.filename)

        local target = unfinished_symlink_target(sub.filename)
        if target then
            unfinished_symlinks[sub.filename] = target
            log("info", "Tracking unfinished symlink: " .. sub.filename)
        elseif sub.filename:match("%.unfinished%.srt$") then
            using_unfinished = true
            final_srt_path = sub.filename:gsub("%.unfinished%.srt$", ".srt")
            log("info", "Tracking unfinished subtitle: " .. sub.filename)
        end
    end

    -- Clean up existing timer
    if auto_reload_timer then
        auto_reload_timer:kill()
        auto_reload_timer = nil
    end
    
    -- Re-enable auto reload if it was enabled
    if auto_reload_enabled then
        mp.add_timeout(1, function()
            reload_all_subs(true, true)
            auto_reload_timer = mp.add_periodic_timer(auto_reload_interval, check_subtitle_changes)
        end)
    end
end)

mp.register_event("shutdown", function()
    if auto_reload_timer then
        auto_reload_timer:kill()
    end
end)

-- Key bindings
mp.add_key_binding("U", "reload-subtitles", function() 
    reload_all_subs(false, false) 
end)

mp.add_key_binding("Alt+r", "toggle-auto-reload-subtitles", toggle_auto_reload)

mp.add_key_binding("Ctrl+u", "force-reload-subtitles", function()
    reload_all_subs(false, true)
end)

-- Initialize
log("info", "Enhanced subtitle reload script loaded (with auto-switch support)")
log("info", "Key bindings: U (reload), Alt+R (toggle auto-reload), Ctrl+U (force reload + rescan)")
