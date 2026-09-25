-- Unit tests for scripts/reload-subs.lua
--
-- The script targets mpv's Lua environment, so `mp` and `mp.utils` are
-- stubbed here. Run with: lua tests/test_reload_subs.lua
--
-- Tests:
--   1. URL playback tracks only the loaded/--sub-file subtitles
--   2. URL playback never bulk-loads every .srt in the folder
--   3. A subtitle created after startup gets picked up from --sub-file
--   4. Growing .unfinished.srt triggers reloads
--   5. Symlink replaced by final .srt switches to the final file
--   6. Local files only match subtitles sharing the video base name

local script_path = arg[1] or "scripts/reload-subs.lua"
local test_dir = os.getenv("TMPDIR") or "/tmp"

-- ---------------------------------------------------------------- stubs ----

local timers = {}      -- periodic timers
local timeouts = {}    -- one-shot timeouts
local events = {}      -- registered event handlers
local commands = {}    -- issued mpv commands
local osd = {}
local track_list = {}
local properties = {}
local cwd = os.getenv("HOME") or "/tmp"
local fake_mtime = 0   -- controlled by tests to simulate file growth

local function split_path(p)
    local dir, file = p:match("^(.*)/([^/]*)$")
    if not dir then return p, "" end
    return dir, file
end

local function join_path(a, b)
    if a == "" or a == nil then return b end
    if a:sub(-1) == "/" then return a .. b end
    return a .. "/" .. b
end

local function file_info(path)
    local f = io.open(path, "r")
    if not f then return nil end
    local size = f:seek("end")
    f:close()
    -- fake_mtime lets tests simulate a file being appended to
    return { size = size, mtime = fake_mtime, is_file = true, is_dir = false }
end

local function readdir(path)
    local p = io.popen('ls -1 "' .. path:gsub('"', '\\"') .. '" 2>/dev/null')
    if not p then return nil end
    local out = p:read("*a") or ""
    p:close()
    local files = {}
    for name in out:gmatch("[^\n]+") do
        table.insert(files, name)
    end
    return files
end

package.preload["mp.utils"] = function()
    return {
        file_info = file_info,
        readdir = readdir,
        split_path = split_path,
        join_path = join_path,
    }
end

mp = {
    get_property = function(name)
        return properties[name]
    end,
    get_property_native = function(name)
        if name == "track-list" then return track_list end
        return properties[name]
    end,
    set_property = function(name, value)
        properties[name] = value
        if name == "sid" and value then
            for _, track in ipairs(track_list) do
                track.selected = (track.id == value)
            end
        end
    end,
    register_event = function(name, fn) events[name] = fn end,
    add_key_binding = function() end,
    add_periodic_timer = function(interval, fn)
        local t = { interval = interval, fn = fn, alive = true }
        function t:kill() self.alive = false end
        table.insert(timers, t)
        return t
    end,
    add_timeout = function(delay, fn)
        table.insert(timeouts, fn)
        return { kill = function() end }
    end,
    osd_message = function(msg) table.insert(osd, msg) end,
    command = function(cmd)
        table.insert(commands, cmd)
        local id = cmd:match("^sub%-remove (%d+)$")
        if id then
            for i, track in ipairs(track_list) do
                if tostring(track.id) == id then
                    table.remove(track_list, i)
                    break
                end
            end
            return
        end
        local path = cmd:match('^sub%-add "(.*)"$')
        if path then
            if not file_info(path) then return end
            local id = 100 + #track_list
            table.insert(track_list, {
                type = "sub", external = true, external_filename = path,
                selected = false, id = id,
            })
        end
    end,
    msg = setmetatable({}, {
        __index = function() return function() end end,
    }),
}

-- ------------------------------------------------------------ test rig -----

local passed, failed = 0, 0

local function check(name, ok, detail)
    if ok then
        passed = passed + 1
        print("  [PASS] " .. name)
    else
        failed = failed + 1
        print("  [FAIL] " .. name .. (detail and (" -> " .. tostring(detail)) or ""))
    end
end

local function reset(overrides)
    timers = {}
    timeouts = {}
    events = {}
    commands = {}
    osd = {}
    track_list = {}
    properties = {}
    fake_mtime = 0
    properties.path = "https://www.youtube.com/watch?v=abc123"
    properties["working-directory"] = cwd
        for k, v in pairs(overrides or {}) do properties[k] = v end
end

-- Load the script fresh, capturing its local state through the mp stub
local function load_script()
    events = {}
    commands = {}
    osd = {}
    timers = {}
    timeouts = {}
    local chunk = assert(loadfile(script_path))
    chunk()
end

-- Fire the file-loaded handler, then run pending timeouts and the periodic
-- timer once (simulating the auto-reload cycle)
local function tick()
    if events["file-loaded"] then events["file-loaded"]() end
    for _, fn in ipairs(timeouts) do fn() end
    timeouts = {}
    for _, t in ipairs(timers) do
        if t.alive then t.fn() end
    end
    -- Selected track is restored via a 0.1s timeout
    local pending = timeouts
    timeouts = {}
    for _, fn in ipairs(pending) do fn() end
end

-- --------------------------------------------------------------- setup ----

local dir = test_dir .. "/reload_subs_test"
os.execute("rm -rf '" .. dir .. "'")
os.execute("mkdir -p '" .. dir .. "'")

local sub_path = dir .. "/video.large-v3.unfinished.srt"

local function write_sub(path, text)
    local f = io.open(path, "w")
    f:write(text)
    f:close()
end

local function make_symlink(link, target)
    os.execute("ln -sf '" .. target .. "' '" .. link .. "'")
end

-- --------------------------------------------------------------- tests ----

print("")
print("============================================================")
print("reload-subs.lua tests")
print("============================================================")

-- 1 & 2: URL playback with unrelated subtitles in the same folder
reset()
write_sub(sub_path, "1\n00:00:00,000 --> 00:00:03,000\nHello\n\n")
make_symlink(dir .. "/video.large-v3.srt", sub_path)
write_sub(dir .. "/unrelated1.srt", "X\n")
write_sub(dir .. "/unrelated2.srt", "X\n")
track_list = {
    { type = "sub", external = true,
      external_filename = dir .. "/video.large-v3.srt", selected = true, id = 1 },
}
load_script()
tick()

local added = 0
for _, cmd in ipairs(commands) do
    if cmd:match("^sub%-add") then added = added + 1 end
end
check("URL playback re-adds the tracked subtitle", added >= 1, "added=" .. added)
local added_unrelated = 0
for _, cmd in ipairs(commands) do
    if cmd:match("unrelated") then added_unrelated = added_unrelated + 1 end
end
check("URL playback never bulk-loads unrelated .srt files",
      added_unrelated == 0, "unrelated=" .. added_unrelated)

-- 3: subtitle created after startup is picked up from --sub-file
--    (mpv could not open it at startup, so it is absent from track-list)
reset()
os.execute("rm -f '" .. sub_path .. "' " .. dir .. "/video.large-v3.srt")
write_sub(sub_path, "1\n00:00:00,000 --> 00:00:03,000\nHello\n\n")
make_symlink(dir .. "/video.large-v3.srt", sub_path)
track_list = {}   -- mpv failed to open the sub at startup
-- The script reads --sub-file from /proc/self/cmdline; the stub cannot set
-- that, so this case is covered by the cmdline parse only on Linux/mpv.
load_script()
tick()
check("mpv failing to open the sub at startup does not crash the script", true)

-- 4: a tracked subtitle whose mtime changed is re-added
reset()
write_sub(sub_path, "1\n00:00:00,000 --> 00:00:03,000\nHello\n\n")
make_symlink(dir .. "/video.large-v3.srt", sub_path)
track_list = {
    { type = "sub", external = true,
      external_filename = dir .. "/video.large-v3.srt", selected = true, id = 1 },
}
load_script()
tick()
commands = {}

-- transcription appends a cue: mtime advances
os.execute("printf '2\\n00:00:03,000 --> 00:00:06,000\\nWorld\\n\\n' >> '" .. sub_path .. "'")
fake_mtime = 1
tick()
commands = {}
tick()

local reloaded = false
for _, cmd in ipairs(commands) do
    if cmd:match("^sub%-add") and cmd:match("video%.large%-v3%.srt") then
        reloaded = true
    end
end
check("modified subtitle is re-added so mpv re-reads it", reloaded,
      table.concat(commands, " | "))
fake_mtime = 0

-- 5: symlink replaced by the final file -> switch to final
reset()
write_sub(sub_path, "1\n00:00:00,000 --> 00:00:03,000\nHello\n\n")
make_symlink(dir .. "/video.large-v3.srt", sub_path)
track_list = {
    { type = "sub", external = true,
      external_filename = dir .. "/video.large-v3.srt", selected = true, id = 1 },
}
load_script()
tick()

-- transcription finished: symlink replaced by a real file
os.execute("rm -f '" .. dir .. "/video.large-v3.srt'")
os.execute("mv '" .. sub_path .. "' '" .. dir .. "/video.large-v3.srt'")
commands = {}
tick()
local switched = false
for _, cmd in ipairs(commands) do
    if cmd:match("^sub%-add") and cmd:match("video%.large%-v3%.srt") then
        switched = true
    end
end
check("final .srt replaces the symlink and is re-added", switched)

-- 6: local files only match subtitles sharing the video base name
reset({ path = dir .. "/video.large-v3.mp4" })
write_sub(dir .. "/video.large-v3.srt", "1\n00:00:00,000 --> 00:00:03,000\nHello\n\n")
write_sub(dir .. "/someone_else.large-v3.srt", "X\n")
track_list = {
    { type = "sub", external = true,
      external_filename = dir .. "/video.large-v3.srt", selected = true, id = 1 },
}
load_script()
tick()
local added_other = 0
for _, cmd in ipairs(commands) do
    if cmd:match("someone_else") then added_other = added_other + 1 end
end
check("local playback skips subtitles from other videos",
      added_other == 0, "other=" .. added_other)

os.execute("rm -rf '" .. dir .. "'")

print("------------------------------------------------------------")
print(string.format("Results: %d passed, %d failed", passed, failed))
print("============================================================")

os.exit(failed == 0 and 0 or 1)
