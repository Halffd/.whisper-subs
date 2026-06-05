#!/usr/bin/env python3
"""
Unified helper file creation for whisper-subs.

Creates player launcher files (.htm, .sh, .bat, .ps1) for a given SRT file,
with support for:
- Multiple media players (mpv, vlc, ffplay, etc.)
- URL resolution from existing HTML files or filenames
- Automatic cleanup of .unfinished.* files when transcription completes
- Subprocess-safe invocation (no import of transcribe/model needed)

All callers should use:
    from helper_files import make_files
    make_files(srt_file, url=url)
"""

import os
import re
import json
import sys
import shutil
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class PlayerType(Enum):
    MPV = "mpv"
    VLC = "vlc"
    FFPLAY = "ffplay"
    MPLAYER = "mplayer"
    CELLULOID = "celluloid"
    SMPLAYER = "smplayer"
    POTPLAYER = "potplayer"
    MPC_HC = "mpc-hc"
    IINA = "iina"


@dataclass
class PlayerConfig:
    name: PlayerType
    executable: str
    sub_flag: str = "--sub-file="
    pause_flag: str = "--pause"
    fullscreen_flag: str = "--fullscreen"
    ipc_flag: str = "--input-ipc-server="
    volume_flag: str = "--volume="
    custom_args: List[str] = field(default_factory=list)

    @classmethod
    def default_configs(cls) -> Dict[PlayerType, 'PlayerConfig']:
        return {
            PlayerType.MPV: cls(
                name=PlayerType.MPV, executable="mpv",
                sub_flag="--sub-file=", pause_flag="--pause",
                fullscreen_flag="--fullscreen", ipc_flag="--input-ipc-server=",
                volume_flag="--volume="
            ),
            PlayerType.VLC: cls(
                name=PlayerType.VLC, executable="vlc",
                sub_flag="--sub-file=", pause_flag="--play-and-pause",
                fullscreen_flag="--fullscreen", ipc_flag="--extraintf=rc --rc-host=",
                volume_flag="--volume="
            ),
            PlayerType.FFPLAY: cls(
                name=PlayerType.FFPLAY, executable="ffplay",
                sub_flag="-sub_file ", pause_flag="-pause",
                fullscreen_flag="-fs", ipc_flag="",
                volume_flag="-volume "
            ),
            PlayerType.MPLAYER: cls(
                name=PlayerType.MPLAYER, executable="mplayer",
                sub_flag="-sub ", pause_flag="-pause",
                fullscreen_flag="-fs", ipc_flag="-input file=",
                volume_flag="-volume "
            ),
            PlayerType.CELLULOID: cls(
                name=PlayerType.CELLULOID, executable="celluloid",
                sub_flag="--sub-file=", pause_flag="--pause",
                fullscreen_flag="--fullscreen", ipc_flag="--socket=",
                volume_flag="--volume="
            ),
            PlayerType.IINA: cls(
                name=PlayerType.IINA, executable="iina",
                sub_flag="--sub-file=", pause_flag="--pause",
                fullscreen_flag="--fullscreen", ipc_flag="--mpv-input-ipc-server=",
                volume_flag="--mpv-volume="
            ),
        }


DEFAULT_PLAYER = PlayerType.MPV
DEFAULT_TEMPLATE_TYPES = ['html', 'sh', 'bat', 'ps1']
DEFAULT_IPC_SERVER = '/tmp/mpvsocket'


def _escape_shell(text: str) -> str:
    return text.replace("'", "'\\''")


def _to_windows_path(path: str) -> str:
    p = Path(path)
    if not p.is_absolute():
        return str(p).replace('/', '\\')
    parts = p.parts
    if len(parts) > 2 and parts[0] == '/' and parts[1] == 'home':
        return f"C:\\Users\\{parts[2]}\\{'\\'.join(parts[3:])}"
    return f"C:\\{'\\'.join(parts[1:])}"


def _clean_basename(subtitle_path: str) -> str:
    name = Path(subtitle_path).stem
    if name.endswith('.unfinished'):
        name = name[:-11]
    return name


def _extract_url_from_html(html_file: str) -> Optional[str]:
    if not os.path.exists(html_file):
        return None
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(r"URL=['\"]([^'\"]+)['\"]", content)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"Error reading HTML file {html_file}: {e}")
    return None


def _extract_video_id(base_name: str) -> str:
    match = re.search(r'[?&]v=([^&\s]+)', base_name)
    if match:
        return match.group(1)
    candidate = base_name.split('_')[0]
    if len(candidate) <= 20:
        return candidate
    return 'video_id_placeholder'


def cleanup_unfinished(srt_file: str) -> None:
    """
    Remove .unfinished.* helper files after transcription completes.

    When a .srt file is finished, any corresponding .unfinished.srt,
    .unfinished.sh, .unfinished.bat, .unfinished.htm, .unfinished.ps1
    should be cleaned up.

    Args:
        srt_file: Path to the finished SRT file (not .unfinished.srt)
    """
    dir_path = os.path.dirname(srt_file) or '.'
    base_name = _clean_basename(srt_file)
    for ext in ['.srt', '.sh', '.bat', '.htm', '.ps1', '.m3u']:
        unfinished_path = os.path.join(dir_path, f"{base_name}.unfinished{ext}")
        if os.path.islink(unfinished_path):
            try:
                os.remove(unfinished_path)
                print(f"Removed unfinished symlink: {unfinished_path}")
            except OSError as e:
                print(f"Warning: Could not remove {unfinished_path}: {e}")
        elif os.path.exists(unfinished_path):
            try:
                os.remove(unfinished_path)
                print(f"Removed unfinished file: {unfinished_path}")
            except OSError as e:
                print(f"Warning: Could not remove {unfinished_path}: {e}")


class HelperFileCreator:
    """
    Creates player launcher files for a given subtitle + URL pair.

    Supports HTML redirect, shell script, batch file, and PowerShell script.
    Only .sh files get executable permission (0o755). All other files use
    default permissions (0o644).
    """

    def __init__(self, srt_file: str, url: str,
                 output_dir: Optional[str] = None,
                 player: PlayerType = DEFAULT_PLAYER,
                 ipc_server: str = DEFAULT_IPC_SERVER,
                 template_types: Optional[List[str]] = None):
        self.srt_file = str(Path(srt_file).resolve())
        self.url = url
        self.base_name = _clean_basename(self.srt_file)
        self.output_dir = Path(output_dir) if output_dir else Path(os.path.dirname(self.srt_file)) or Path('.')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.player = player
        self.player_config = PlayerConfig.default_configs().get(player)
        self.ipc_server = ipc_server
        self.template_types = template_types or DEFAULT_TEMPLATE_TYPES
        self.generated: Dict[str, Optional[Path]] = {}

    def create_html(self) -> Optional[Path]:
        html_file = self.output_dir / f"{self.base_name}.htm"
        try:
            html_file.write_text(
                f"<!DOCTYPE html>\n<html>\n"
                f"<head><meta http-equiv=\"refresh\" content=\"0; URL='{self.url}'\" /></head>\n"
                f"<body></body>\n</html>",
                encoding='utf-8'
            )
            return html_file
        except Exception as e:
            print(f"Error creating HTML: {e}")
            return None

    def create_shell_script(self) -> Optional[Path]:
        sh_file = self.output_dir / f"{self.base_name}.sh"
        try:
            subtitle_linux = str(self.srt_file).replace('\\', '/')
            escaped_url = _escape_shell(self.url)
            escaped_sub = _escape_shell(subtitle_linux)

            cfg = self.player_config
            args_parts = []
            if cfg.pause_flag:
                args_parts.append(cfg.pause_flag)
            if self.ipc_server and cfg.ipc_flag:
                args_parts.append(f"{cfg.ipc_flag}{self.ipc_server}")
            args_parts.append(f"--sub-file='{escaped_sub}'")
            args_str = ' '.join(args_parts)

            sh_file.write_text(
                f"#!/bin/bash\n"
                f"{cfg.executable} '{escaped_url}' {args_str} \"$@\"\n",
                encoding='utf-8'
            )
            sh_file.chmod(0o755)
            return sh_file
        except Exception as e:
            print(f"Error creating shell script: {e}")
            return None

    def create_batch_file(self) -> Optional[Path]:
        bat_file = self.output_dir / f"{self.base_name}.bat"
        try:
            windows_sub = _to_windows_path(self.srt_file)
            cfg = self.player_config
            pause_flag = cfg.pause_flag if cfg.pause_flag else ''
            ipc_arg = f"{cfg.ipc_flag}{self.ipc_server}" if self.ipc_server and cfg.ipc_flag else ''

            bat_file.write_text(
                f"@echo off\n"
                f"setlocal DisableDelayedExpansion\n"
                f"{cfg.executable} \"{self.url}\" {pause_flag} {ipc_arg} "
                f"--sub-file=\"{windows_sub}\" %*\n",
                encoding='utf-8'
            )
            return bat_file
        except Exception as e:
            print(f"Error creating batch file: {e}")
            return None

    def create_powershell(self) -> Optional[Path]:
        ps_file = self.output_dir / f"{self.base_name}.ps1"
        try:
            windows_sub = _to_windows_path(self.srt_file)
            cfg = self.player_config
            ps_file.write_text(
                f"& {cfg.executable} '{self.url}' {cfg.pause_flag} "
                f"--sub-file='{windows_sub}' @args\n",
                encoding='utf-8'
            )
            return ps_file
        except Exception as e:
            print(f"Error creating PowerShell: {e}")
            return None

    def create_playlist(self) -> Optional[Path]:
        m3u_file = self.output_dir / f"{self.base_name}.m3u"
        try:
            subtitle_linux = str(self.srt_file).replace('\\', '/')
            m3u_file.write_text(
                f"#EXTM3U\n#EXTINF:-1,{self.base_name}\n{self.url}\n"
                f"#EXTINF:-1,Subtitles\n{subtitle_linux}\n",
                encoding='utf-8'
            )
            return m3u_file
        except Exception as e:
            print(f"Error creating playlist: {e}")
            return None

    def create_json_config(self, extra: Optional[Dict[str, Any]] = None) -> Optional[Path]:
        json_file = self.output_dir / f"{self.base_name}.mpv.json"
        try:
            config = {
                'version': '2.0',
                'generated': datetime.now().isoformat(),
                'url': self.url,
                'subtitle': self.srt_file,
                'player': self.player.value,
                'base_name': self.base_name,
            }
            if extra:
                config.update(extra)
            json_file.write_text(json.dumps(config, indent=2), encoding='utf-8')
            return json_file
        except Exception as e:
            print(f"Error creating JSON config: {e}")
            return None

    def generate(self) -> Dict[str, Optional[Path]]:
        creators = {
            'html': self.create_html,
            'sh': self.create_shell_script,
            'bat': self.create_batch_file,
            'ps1': self.create_powershell,
            'm3u': self.create_playlist,
            'json': self.create_json_config,
        }
        for t in self.template_types:
            if t in creators:
                self.generated[t] = creators[t]()
        return self.generated


def make_files(srt_file: str, url: Optional[str] = None,
               player: str = 'mpv',
               template_types: Optional[List[str]] = None) -> Dict[str, Optional[Path]]:
    """
    Create helper files (HTML, .sh, .bat, .ps1) for the given SRT file.

    This is the primary entry point used by transcribe.py, whisper_subs.py,
    and the GUI apps. It resolves the URL if not provided, delegates to
    HelperFileCreator, and cleans up .unfinished.* files when called for
    a finished SRT (not .unfinished.srt).

    Args:
        srt_file: Path to the SRT file (finished or .unfinished.srt)
        url: Video URL. If None, attempts to extract from existing HTML or filename.
        player: Player name string (default 'mpv')
        template_types: List of template types to create (default: html, sh, bat, ps1)

    Returns:
        Dict mapping template type to created file Path (or None on failure)
    """
    if not srt_file:
        print("No SRT file provided")
        return {}

    try:
        print(f"Creating helper files for {srt_file}")

        is_unfinished = '.unfinished' in os.path.basename(srt_file)

        if not os.path.exists(srt_file):
            os.makedirs(os.path.dirname(srt_file) or '.', exist_ok=True)
            with open(srt_file, 'w', encoding='utf-8') as f:
                f.write('Transcription in progress...')

        dir_path = os.path.dirname(srt_file) or '.'
        base_name = _clean_basename(srt_file)

        if url:
            print(f"Using provided URL: {url}")
        else:
            html_path = os.path.join(dir_path, f"{base_name}.htm")
            url = _extract_url_from_html(html_path)
            if not url and is_unfinished:
                url = _extract_video_id(base_name)
            if url:
                print(f"Resolved URL: {url}")

        if not url:
            print(f"No URL available for helper files (srt_file={srt_file})")
            return {}

        try:
            player_type = PlayerType(player.lower())
        except ValueError:
            player_type = DEFAULT_PLAYER

        creator = HelperFileCreator(
            srt_file=srt_file, url=url,
            output_dir=dir_path,
            player=player_type,
            template_types=template_types or DEFAULT_TEMPLATE_TYPES,
        )
        results = creator.generate()

        if not is_unfinished:
            cleanup_unfinished(srt_file)

        return results

    except Exception as e:
        print(f"Error in make_files for {srt_file}: {e}")
        return {}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Create player helper files for subtitles')
    parser.add_argument('srt_file', help='Path to SRT file')
    parser.add_argument('--url', help='Video URL (auto-detected if not provided)')
    parser.add_argument('--player', default='mpv',
                        choices=[p.value for p in PlayerType],
                        help='Media player to use')
    parser.add_argument('-t', '--templates', nargs='+',
                        default=DEFAULT_TEMPLATE_TYPES,
                        choices=['html', 'sh', 'bat', 'ps1', 'm3u', 'json'],
                        help='Template types to generate')
    parser.add_argument('--cleanup', action='store_true',
                        help='Only clean up .unfinished files, do not generate')
    args = parser.parse_args()

    if args.cleanup:
        cleanup_unfinished(args.srt_file)
    else:
        results = make_files(args.srt_file, url=args.url,
                             player=args.player, template_types=args.templates)
        if results:
            print(f"Generated {len([v for v in results.values() if v])} files")
            for ftype, fpath in results.items():
                if fpath:
                    print(f"  {ftype}: {fpath}")
