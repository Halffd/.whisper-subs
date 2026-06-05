#!/usr/bin/env python3
"""
MPV Templater - Generate playable templates for videos with subtitles
Supports HTML redirects, shell scripts, batch files, and PowerShell scripts
"""

import os
import sys
import json
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class MPVTemplate:
    """Configuration for MPV template generation."""
    url: str
    subtitle_path: Path
    output_dir: Path
    mpv_args: Dict[str, Any] = field(default_factory=lambda: {
        'pause': True,
        'input_ipc_server': '/tmp/mpvsocket',
        'keep_open': False,
        'fullscreen': False,
        'volume': 100
    })
    template_types: list = field(default_factory=lambda: ['html', 'sh', 'bat', 'ps1'])

    def __post_init__(self):
        self.output_dir = Path(self.output_dir)
        self.subtitle_path = Path(os.path.abspath(self.subtitle_path))
        self.base_name = self._clean_basename()
        self.subtitle_path_linux = str(self.subtitle_path).replace('\\', '/')

    def _clean_basename(self) -> str:
        """Remove .unfinished suffix and get clean name."""
        name = self.subtitle_path.stem
        return name[:-11] if name.endswith('.unfinished') else name

    def _build_mpv_command(self) -> str:
        """Build the MPV command with all arguments."""
        args = []

        # Basic arguments
        if self.mpv_args.get('pause', True):
            args.append('--pause')

        if self.mpv_args.get('input_ipc_server'):
            args.append(f"--input-ipc-server={self.mpv_args['input_ipc_server']}")

        if self.mpv_args.get('keep_open', False):
            args.append('--keep-open=always')

        if self.mpv_args.get('fullscreen', False):
            args.append('--fullscreen')

        if self.mpv_args.get('volume', 100) != 100:
            args.append(f"--volume={self.mpv_args['volume']}")

        # Subtitle specific arguments
        args.append(f"--sub-file='{self._escape(self.subtitle_path_linux)}'")

        # Additional custom args
        if self.mpv_args.get('custom_args'):
            args.extend(self.mpv_args['custom_args'])

        # Build command
        args_str = ' '.join(args)
        return f"mpv '{self._escape(self.url)}' {args_str} \"$@\""

    @staticmethod
    def _escape(text: str) -> str:
        """Escape for shell single quotes."""
        return text.replace("'", "'\\''")

    @staticmethod
    def _to_windows_path(path: str) -> str:
        """Convert Linux path to Windows format."""
        path = Path(path)
        if not path.is_absolute():
            return str(path).replace('/', '\\')

        parts = path.parts
        # Handle WSL /home/username paths
        if len(parts) > 2 and parts[0] == '/' and parts[1] == 'home':
            return f"C:\\Users\\{parts[2]}\\{'\\'.join(parts[3:])}"
        # Generic absolute path
        return f"C:\\{'\\'.join(parts[1:])}"

    def create_html(self) -> Optional[Path]:
        """Create HTML redirect file."""
        html_file = self.output_dir / f"{self.base_name}.htm"
        try:
            content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="0; URL='{self.url}'">
    <title>Redirecting to {self.base_name}</title>
</head>
<body>
    <p>Redirecting to <a href="{self.url}">{self.url}</a>...</p>
</body>
</html>"""
            html_file.write_text(content, encoding='utf-8')
            return html_file
        except Exception as e:
            print(f"Error creating HTML: {e}")
            return None

    def create_shell_script(self) -> Optional[Path]:
        """Create bash shell script."""
        sh_file = self.output_dir / f"{self.base_name}.sh"
        try:
            command = self._build_mpv_command()
            content = f"""#!/bin/bash
# MPV Template for {self.base_name}
# Generated: {datetime.now().isoformat()}
# URL: {self.url}
# Subtitle: {self.subtitle_path_linux}

{command}

# Cleanup unfinished marker if exists
if [[ "$0" == *".unfinished."* ]]; then
    rm -f "$0"
fi
"""
            sh_file.write_text(content, encoding='utf-8')
            sh_file.chmod(0o755)

            # Create unfinished version
            unfinished = sh_file.with_stem(f"{sh_file.stem}.unfinished")
            if unfinished.exists():
                unfinished.unlink()
            unfinished.symlink_to(sh_file)

            return sh_file
        except Exception as e:
            print(f"Error creating shell script: {e}")
            return None

    def create_batch_file(self) -> Optional[Path]:
        """Create Windows batch file."""
        bat_file = self.output_dir / f"{self.base_name}.bat"
        try:
            windows_sub = self._to_windows_path(str(self.subtitle_path))
            pause_flag = '--pause' if self.mpv_args.get('pause', True) else ''
            ipc_server = f"--input-ipc-server={self.mpv_args['input_ipc_server']}" if self.mpv_args.get('input_ipc_server') else ''

            content = f"""@echo off
REM MPV Template for {self.base_name}
REM Generated: {datetime.now().isoformat()}
REM URL: {self.url}
REM Subtitle: {windows_sub}

setlocal DisableDelayedExpansion
mpv "{self.url}" {pause_flag} {ipc_server} --sub-file="{windows_sub}" %*
endlocal

REM Cleanup unfinished marker
if "%~nx0"=="*.unfinished.*" (
    del "%~f0"
)
"""
            bat_file.write_text(content, encoding='utf-8')

            # Create unfinished version
            unfinished = bat_file.with_stem(f"{bat_file.stem}.unfinished")
            if unfinished.exists():
                unfinished.unlink()
            try:
                unfinished.symlink_to(bat_file)
            except OSError:
                # Symlinks might not be supported on some Windows setups
                import shutil
                shutil.copy2(bat_file, unfinished)

            return bat_file
        except Exception as e:
            print(f"Error creating batch file: {e}")
            return None

    def create_powershell(self) -> Optional[Path]:
        """Create PowerShell script."""
        ps_file = self.output_dir / f"{self.base_name}.ps1"
        try:
            windows_sub = self._to_windows_path(str(self.subtitle_path))
            pause_flag = $'--pause' if self.mpv_args.get('pause', True) else ''

            content = f"""# MPV Template for {self.base_name}
# Generated: {datetime.now().isoformat()}
# URL: {self.url}
# Subtitle: {windows_sub}

$url = '{self.url}'
$subFile = '{windows_sub}'
$mpvArgs = @(
    $url,
    '{pause_flag}',
    '--sub-file=$subFile'
)

if ($args.Count -gt 0) {{
    $mpvArgs += $args
}}

& mpv $mpvArgs

# Cleanup unfinished marker
if ($MyInvocation.MyCommand.Name -like '*.unfinished.*') {{
    Remove-Item -Path $MyInvocation.MyCommand.Path -Force
}}
"""
            ps_file.write_text(content, encoding='utf-8')
            return ps_file
        except Exception as e:
            print(f"Error creating PowerShell: {e}")
            return None

    def create_playlist(self) -> Optional[Path]:
        """Create an M3U playlist file."""
        playlist_file = self.output_dir / f"{self.base_name}.m3u"
        try:
            content = f"""#EXTM3U
#EXTINF:-1,{self.base_name}
{self.url}
#EXTINF:-1,Subtitles
{self.subtitle_path_linux}
"""
            playlist_file.write_text(content, encoding='utf-8')
            return playlist_file
        except Exception as e:
            print(f"Error creating playlist: {e}")
            return None

    def create_json_config(self) -> Optional[Path]:
        """Create JSON configuration file."""
        json_file = self.output_dir / f"{self.base_name}.mpv.json"
        try:
            config = {
                'template_version': '1.0',
                'generated': datetime.now().isoformat(),
                'url': self.url,
                'subtitle': str(self.subtitle_path),
                'mpv_args': self.mpv_args,
                'base_name': self.base_name
            }
            json_file.write_text(json.dumps(config, indent=2), encoding='utf-8')
            return json_file
        except Exception as e:
            print(f"Error creating JSON config: {e}")
            return None

    def create_wrapper_script(self) -> Optional[Path]:
        """Create a universal wrapper script that detects OS."""
        wrapper_file = self.output_dir / f"{self.base_name}"
        if sys.platform == 'win32':
            wrapper_file = self.output_dir / f"{self.base_name}.cmd"

        try:
            content = f"""#!/usr/bin/env bash
# Universal MPV Template Wrapper
# Generated: {datetime.now().isoformat()}

# Detect OS and run appropriate script
case "$(uname -s)" in
    Linux*|Darwin*)
        exec "{self.output_dir}/{self.base_name}.sh" "$@"
        ;;
    MINGW*|CYGWIN*|MSYS*)
        exec "{self.output_dir}/{self.base_name}.bat" "$@"
        ;;
    *)
        echo "Unsupported OS: $(uname -s)"
        exit 1
        ;;
esac
"""
            wrapper_file.write_text(content, encoding='utf-8')
            if not sys.platform == 'win32':
                wrapper_file.chmod(0o755)
            return wrapper_file
        except Exception as e:
            print(f"Error creating wrapper script: {e}")
            return None

    def generate(self) -> Dict[str, Optional[Path]]:
        """Generate all requested template files."""
        results = {}

        template_creators = {
            'html': self.create_html,
            'sh': self.create_shell_script,
            'bat': self.create_batch_file,
            'ps1': self.create_powershell,
            'm3u': self.create_playlist,
            'json': self.create_json_config,
            'wrapper': self.create_wrapper_script
        }

        for template_type in self.template_types:
            if template_type in template_creators:
                results[template_type] = template_creators[template_type]()

        return results


# Convenience functions
def create_mpv_template(url: str, subtitle_file: str, output_dir: str = '.', **kwargs) -> Dict[str, Optional[Path]]:
    """Create MPV templates with one function call."""
    template = MPVTemplate(
        url=url,
        subtitle_path=Path(subtitle_file),
        output_dir=Path(output_dir),
        mpv_args=kwargs.get('mpv_args', {}),
        template_types=kwargs.get('template_types', ['html', 'sh', 'bat'])
    )
    return template.generate()


def create_playlist_from_urls(urls: list, output_file: str = 'playlist.m3u') -> Path:
    """Create an M3U playlist from multiple URLs."""
    playlist = Path(output_file)
    content = ['#EXTM3U']

    for i, url in enumerate(urls):
        content.append(f'#EXTINF:-1,Video {i+1}')
        content.append(url)

    playlist.write_text('\n'.join(content), encoding='utf-8')
    return playlist


# CLI interface
def main():
    """Command-line interface for MPV Templater."""
    import argparse

    parser = argparse.ArgumentParser(description='Generate MPV templates for videos with subtitles')
    parser.add_argument('url', help='Video URL or path')
    parser.add_argument('subtitle', help='Subtitle file path')
    parser.add_argument('-o', '--output', default='.', help='Output directory')
    parser.add_argument('-t', '--templates', nargs='+',
                       default=['html', 'sh', 'bat'],
                       choices=['html', 'sh', 'bat', 'ps1', 'm3u', 'json', 'wrapper'],
                       help='Template types to generate')
    parser.add_argument('--no-pause', action='store_true', help='Start playing immediately')
    parser.add_argument('--fullscreen', action='store_true', help='Start in fullscreen')
    parser.add_argument('--volume', type=int, default=100, help='Initial volume')
    parser.add_argument('--ipc-server', default='/tmp/mpvsocket', help='IPC server socket path')

    args = parser.parse_args()

    mpv_args = {
        'pause': not args.no_pause,
        'fullscreen': args.fullscreen,
        'volume': args.volume,
        'input_ipc_server': args.ipc_server
    }

    template = MPVTemplate(
        url=args.url,
        subtitle_path=Path(args.subtitle),
        output_dir=Path(args.output),
        mpv_args=mpv_args,
        template_types=args.templates
    )

    results = template.generate()

    print(f"\n✓ Generated templates for {template.base_name}")
    for template_type, path in results.items():
        if path:
            print(f"  → {template_type}: {path}")


if __name__ == '__main__':
    main()
#!/usr/bin/env python3
"""
MPV Templater with Unfinished File Management and Multi-Player Support
"""

import os
import sys
import json
import shutil
import stat
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List, Union, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import subprocess
import tempfile


class PlayerType(Enum):
    """Supported media players."""
    MPV = "mpv"
    VLC = "vlc"
    FFPLAY = "ffplay"
    MPLAYER = "mplayer"
    CELLULOID = "celluloid"
    SMPLAYER = "smplayer"
    POTPLAYER = "potplayer"  # Windows
    MPC_HC = "mpc-hc"  # Windows
    IINA = "iina"  # macOS


@dataclass
class PlayerConfig:
    """Configuration for a media player."""
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
        """Get default configurations for all supported players."""
        return {
            PlayerType.MPV: cls(
                name=PlayerType.MPV,
                executable="mpv",
                sub_flag="--sub-file=",
                pause_flag="--pause",
                fullscreen_flag="--fullscreen",
                ipc_flag="--input-ipc-server=",
                volume_flag="--volume="
            ),
            PlayerType.VLC: cls(
                name=PlayerType.VLC,
                executable="vlc",
                sub_flag="--sub-file=",
                pause_flag="--play-and-pause",
                fullscreen_flag="--fullscreen",
                ipc_flag="--extraintf=rc --rc-host=",
                volume_flag="--volume="
            ),
            PlayerType.FFPLAY: cls(
                name=PlayerType.FFPLAY,
                executable="ffplay",
                sub_flag="-sub_file ",
                pause_flag="-pause",
                fullscreen_flag="-fs",
                ipc_flag="",
                volume_flag="-volume "
            ),
            PlayerType.MPLAYER: cls(
                name=PlayerType.MPLAYER,
                executable="mplayer",
                sub_flag="-sub ",
                pause_flag="-pause",
                fullscreen_flag="-fs",
                ipc_flag="-input file=",
                volume_flag="-volume "
            ),
            PlayerType.CELLULOID: cls(
                name=PlayerType.CELLULOID,
                executable="celluloid",
                sub_flag="--sub-file=",
                pause_flag="--pause",
                fullscreen_flag="--fullscreen",
                ipc_flag="--socket=",
                volume_flag="--volume="
            ),
            PlayerType.IINA: cls(
                name=PlayerType.IINA,
                executable="iina",
                sub_flag="--sub-file=",
                pause_flag="--pause",
                fullscreen_flag="--fullscreen",
                ipc_flag="--mpv-input-ipc-server=",
                volume_flag="--mpv-volume="
            )
        }


class UnfinishedFileManager:
    """
    Manages unfinished files with symlinks/hardlinks.
    Provides methods to add, remove, link, and unlink unfinished markers.
    """
    
    def __init__(self, base_dir: Optional[Path] = None, use_symlinks: bool = True):
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.use_symlinks = use_symlinks
        self._unfinished_files: Dict[Path, Path] = {}  # target -> unfinished link
        
    def add_unfinished_marker(self, target_file: Union[str, Path]) -> Optional[Path]:
        """
        Add an unfinished marker for a target file.
        
        Args:
            target_file: Path to the target file
            
        Returns:
            Path to the unfinished marker file, or None if failed
        """
        target = Path(target_file)
        if not target.exists():
            raise FileNotFoundError(f"Target file does not exist: {target}")
        
        # Create unfinished marker path
        unfinished = self._get_unfinished_path(target)
        
        # Remove existing if present
        self.remove_unfinished_marker(unfinished)
        
        # Create link
        if self.use_symlinks:
            try:
                unfinished.symlink_to(target)
            except OSError:
                # Fallback to hard link or copy
                try:
                    os.link(target, unfinished)
                except OSError:
                    shutil.copy2(target, unfinished)
        else:
            # Create a copy or hard link
            try:
                os.link(target, unfinished)
            except OSError:
                shutil.copy2(target, unfinished)
        
        self._unfinished_files[target] = unfinished
        return unfinished
    
    def remove_unfinished_marker(self, unfinished_file: Union[str, Path]) -> bool:
        """
        Remove an unfinished marker file.
        
        Args:
            unfinished_file: Path to the unfinished marker
            
        Returns:
            True if removed, False otherwise
        """
        path = Path(unfinished_file)
        
        if not path.exists():
            return False
        
        try:
            if path.is_symlink():
                path.unlink()
            elif path.is_file():
                path.unlink()
            else:
                return False
                
            # Remove from tracking
            for target, unfinished in list(self._unfinished_files.items()):
                if unfinished == path:
                    del self._unfinished_files[target]
                    break
            
            return True
        except OSError:
            return False
    
    def link_unfinished_to(self, target_file: Union[str, Path], 
                           unfinished_file: Union[str, Path]) -> bool:
        """
        Link an unfinished marker to a target file.
        
        Args:
            target_file: The target file to link to
            unfinished_file: The unfinished marker file path
            
        Returns:
            True if linked successfully
        """
        target = Path(target_file)
        unfinished = Path(unfinished_file)
        
        if not target.exists():
            raise FileNotFoundError(f"Target does not exist: {target}")
        
        # Remove existing unfinished file
        if unfinished.exists():
            self.remove_unfinished_marker(unfinished)
        
        # Create link
        try:
            if self.use_symlinks:
                unfinished.symlink_to(target)
            else:
                os.link(target, unfinished)
            self._unfinished_files[target] = unfinished
            return True
        except OSError:
            return False
    
    def unlink_unfinished(self, unfinished_file: Union[str, Path]) -> bool:
        """
        Remove an unfinished marker without affecting the target.
        Alias for remove_unfinished_marker.
        
        Args:
            unfinished_file: Path to the unfinished marker
            
        Returns:
            True if unlinked successfully
        """
        return self.remove_unfinished_marker(unfinished_file)
    
    def get_unfinished_files(self) -> Dict[Path, Path]:
        """
        Get all tracked unfinished files.
        
        Returns:
            Dictionary mapping target -> unfinished marker
        """
        return self._unfinished_files.copy()
    
    def cleanup_orphaned(self) -> List[Path]:
        """
        Remove orphaned unfinished markers where target no longer exists.
        
        Returns:
            List of removed marker paths
        """
        removed = []
        for target, unfinished in list(self._unfinished_files.items()):
            if not target.exists():
                if self.remove_unfinished_marker(unfinished):
                    removed.append(unfinished)
        return removed
    
    def list_unfinished(self) -> List[Path]:
        """
        List all unfinished markers in base directory.
        
        Returns:
            List of unfinished marker paths
        """
        pattern = "*.unfinished.*"
        return list(self.base_dir.glob(pattern))
    
    def complete_unfinished(self, unfinished_file: Union[str, Path]) -> bool:
        """
        Mark an unfinished file as complete by removing the marker.
        
        Args:
            unfinished_file: Path to the unfinished marker
            
        Returns:
            True if completed successfully
        """
        return self.remove_unfinished_marker(unfinished_file)
    
    def _get_unfinished_path(self, target: Path) -> Path:
        """Generate unfinished marker path for a target file."""
        stem = target.stem
        if not stem.endswith('.unfinished'):
            stem = f"{stem}.unfinished"
        return target.parent / f"{stem}{target.suffix}"
    
    def create_wrapper_script(self, target_file: Path, 
                              cleanup_after: bool = True) -> Path:
        """
        Create a wrapper script that auto-cleans the unfinished marker.
        
        Args:
            target_file: The target executable/script
            cleanup_after: Whether to clean up after execution
            
        Returns:
            Path to the wrapper script
        """
        wrapper = target_file.parent / f"{target_file.stem}.wrapper.sh"
        unfinished = self._get_unfinished_path(target_file)
        
        content = f"""#!/bin/bash
# Auto-cleanup wrapper for {target_file.name}
UNFINISHED="{unfinished}"
TARGET="{target_file}"

# Remove unfinished marker when script exits
cleanup() {{
    rm -f "$UNFINISHED"
}}
trap cleanup EXIT

# Execute target
exec "$TARGET" "$@"
"""
        wrapper.write_text(content)
        wrapper.chmod(0o755)
        return wrapper


class MPVTemplater:
    """
    Advanced MPV Templater with multi-player support and unfinished file management.
    """
    
    def __init__(self, 
                 url: str, 
                 subtitle_path: Union[str, Path],
                 output_dir: Union[str, Path] = '.',
                 player: Union[PlayerType, str] = PlayerType.MPV,
                 unfinished_manager: Optional[UnfinishedFileManager] = None):
        """
        Initialize the MPV Templater.
        
        Args:
            url: Video URL or file path
            subtitle_path: Path to subtitle file
            output_dir: Output directory for templates
            player: Media player to use
            unfinished_manager: Optional unfinished file manager
        """
        self.url = url
        self.subtitle_path = Path(os.path.abspath(subtitle_path))
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Set up player
        if isinstance(player, str):
            try:
                self.player_type = PlayerType(player.lower())
            except ValueError:
                raise ValueError(f"Unsupported player: {player}")
        else:
            self.player_type = player
        
        self.player_config = PlayerConfig.default_configs().get(self.player_type)
        if not self.player_config:
            raise ValueError(f"No configuration for player: {self.player_type}")
        
        # Set up unfinished manager
        self.unfinished_manager = unfinished_manager or UnfinishedFileManager(self.output_dir)
        
        # Get base name
        self.base_name = self._clean_basename()
        
        # Store generated files
        self.generated_files: Dict[str, Path] = {}
        
    def _clean_basename(self) -> str:
        """Extract clean base name without .unfinished suffix."""
        name = self.subtitle_path.stem
        if name.endswith('.unfinished'):
            name = name[:-11]  # Remove '.unfinished'
        return name
    
    def _escape_for_shell(self, text: str) -> str:
        """Escape text for shell single quotes."""
        return text.replace("'", "'\\''")
    
    def _to_windows_path(self, path: str) -> str:
        """Convert Linux path to Windows format."""
        path = Path(path)
        if not path.is_absolute():
            return str(path).replace('/', '\\')
        
        parts = path.parts
        if len(parts) > 2 and parts[0] == '/' and parts[1] == 'home':
            return f"C:\\Users\\{parts[2]}\\{'\\'.join(parts[3:])}"
        return f"C:\\{'\\'.join(parts[1:])}"
    
    def _build_player_command(self, extra_args: Optional[List[str]] = None) -> str:
        """
        Build the player command with all arguments.
        
        Args:
            extra_args: Additional arguments to pass to the player
            
        Returns:
            Formatted command string
        """
        args = []
        
        # Add pause flag if available
        if self.player_config.pause_flag:
            args.append(self.player_config.pause_flag)
        
        # Add subtitle file
        subtitle_path = self._escape_for_shell(str(self.subtitle_path))
        args.append(f"{self.player_config.sub_flag}'{subtitle_path}'")
        
        # Add custom arguments
        if extra_args:
            args.extend(extra_args)
        
        # Build command
        player_cmd = self.player_config.executable
        args_str = ' '.join(args)
        url_escaped = self._escape_for_shell(self.url)
        
        return f"{player_cmd} '{url_escaped}' {args_str} \"$@\""
    
    def create_shell_script(self, auto_cleanup: bool = True) -> Path:
        """
        Create a shell script for the configured player.
        
        Args:
            auto_cleanup: Whether to auto-cleanup unfinished marker
            
        Returns:
            Path to the created script
        """
        sh_file = self.output_dir / f"{self.base_name}.sh"
        command = self._build_player_command()
        
        # Create unfinished marker
        if auto_cleanup:
            unfinished = self.unfinished_manager.add_unfinished_marker(sh_file)
            cleanup_code = f"""
# Auto-cleanup unfinished marker
if [ -f "{unfinished}" ]; then
    rm -f "{unfinished}"
fi
"""
        else:
            cleanup_code = ""
        
        content = f"""#!/bin/bash
# MPV Template for {self.base_name}
# Player: {self.player_type.value}
# Generated: {datetime.now().isoformat()}
# URL: {self.url}
# Subtitle: {self.subtitle_path}

{command}
{cleanup_code}
"""
        sh_file.write_text(content, encoding='utf-8')
        sh_file.chmod(0o755)
        
        return sh_file
    
    def create_batch_file(self, auto_cleanup: bool = True) -> Path:
        """
        Create a Windows batch file.
        
        Args:
            auto_cleanup: Whether to auto-cleanup unfinished marker
            
        Returns:
            Path to the batch file
        """
        bat_file = self.output_dir / f"{self.base_name}.bat"
        windows_sub = self._to_windows_path(str(self.subtitle_path))
        
        content = f"""@echo off
REM MPV Template for {self.base_name}
REM Player: {self.player_type.value}
REM Generated: {datetime.now().isoformat()}
REM URL: {self.url}
REM Subtitle: {windows_sub}

{self.player_config.executable} "{self.url}" {self.player_config.pause_flag} {self.player_config.sub_flag}"{windows_sub}" %*
"""
        bat_file.write_text(content, encoding='utf-8')
        
        if auto_cleanup:
            self.unfinished_manager.add_unfinished_marker(bat_file)
        
        return bat_file
    
    def create_powershell(self, auto_cleanup: bool = True) -> Path:
        """
        Create a PowerShell script.
        
        Args:
            auto_cleanup: Whether to auto-cleanup unfinished marker
            
        Returns:
            Path to the PowerShell script
        """
        ps_file = self.output_dir / f"{self.base_name}.ps1"
        windows_sub = self._to_windows_path(str(self.subtitle_path))
        
        content = f"""# MPV Template for {self.base_name}
# Player: {self.player_type.value}
# Generated: {datetime.now().isoformat()}
# URL: {self.url}
# Subtitle: {windows_sub}

$url = '{self.url}'
$subFile = '{windows_sub}'
$player = '{self.player_config.executable}'

& $player $url {self.player_config.pause_flag} {self.player_config.sub_flag}$subFile $args
"""
        ps_file.write_text(content, encoding='utf-8')
        
        if auto_cleanup:
            self.unfinished_manager.add_unfinished_marker(ps_file)
        
        return ps_file
    
    def create_playlist(self) -> Path:
        """Create an M3U playlist file."""
        playlist = self.output_dir / f"{self.base_name}.m3u"
        
        content = f"""#EXTM3U
#EXTINF:-1,{self.base_name}
{self.url}
#EXTINF:-1,Subtitles
{self.subtitle_path}
"""
        playlist.write_text(content, encoding='utf-8')
        return playlist
    
    def create_json_config(self) -> Path:
        """Create JSON configuration file."""
        json_file = self.output_dir / f"{self.base_name}.json"
        
        config = {
            'version': '2.0',
            'generated': datetime.now().isoformat(),
            'url': self.url,
            'subtitle': str(self.subtitle_path),
            'player': self.player_type.value,
            'base_name': self.base_name,
            'output_dir': str(self.output_dir)
        }
        
        json_file.write_text(json.dumps(config, indent=2), encoding='utf-8')
        return json_file
    
    def create_all(self, template_types: Optional[List[str]] = None) -> Dict[str, Path]:
        """
        Create all template files.
        
        Args:
            template_types: List of template types to create
            
        Returns:
            Dictionary mapping type to file path
        """
        if template_types is None:
            template_types = ['sh', 'bat', 'ps1', 'm3u', 'json']
        
        creators = {
            'sh': self.create_shell_script,
            'bat': self.create_batch_file,
            'ps1': self.create_powershell,
            'm3u': self.create_playlist,
            'json': self.create_json_config
        }
        
        for template_type in template_types:
            if template_type in creators:
                self.generated_files[template_type] = creators[template_type]()
        
        return self.generated_files
    
    def cleanup_unfinished(self) -> List[Path]:
        """
        Clean up all unfinished markers for this template.
        
        Returns:
            List of removed files
        """
        removed = []
        for file in self.generated_files.values():
            if self.unfinished_manager.complete_unfinished(file):
                removed.append(file)
        return removed
    
    def play(self, extra_args: Optional[List[str]] = None) -> subprocess.CompletedProcess:
        """
        Play the video immediately with the configured player.
        
        Args:
            extra_args: Additional arguments for the player
            
        Returns:
            Completed process result
        """
        cmd = self._build_player_command(extra_args).split()
        return subprocess.run(cmd, capture_output=True, text=True)


class MultiPlayerManager:
    """
    Manager for handling multiple players and template generation.
    """
    
    def __init__(self, base_dir: Union[str, Path] = '.'):
        self.base_dir = Path(base_dir)
        self.templates: Dict[str, MPVTemplater] = {}
        self.unfinished_manager = UnfinishedFileManager(base_dir)
        
    def create_multi_player_templates(self,
                                     url: str,
                                     subtitle_path: Union[str, Path],
                                     players: Optional[List[PlayerType]] = None,
                                     output_subdir: str = 'templates') -> Dict[PlayerType, MPVTemplater]:
        """
        Create templates for multiple players simultaneously.
        
        Args:
            url: Video URL
            subtitle_path: Subtitle file path
            players: List of players to generate templates for
            output_subdir: Subdirectory for output
            
        Returns:
            Dictionary mapping player to templater instance
        """
        if players is None:
            players = [PlayerType.MPV, PlayerType.VLC, PlayerType.FFPLAY]
        
        output_dir = self.base_dir / output_subdir
        output_dir.mkdir(parents=True, exist_ok=True)
        
        results = {}
        for player in players:
            templater = MPVTemplater(
                url=url,
                subtitle_path=subtitle_path,
                output_dir=output_dir / player.value,
                player=player,
                unfinished_manager=self.unfinished_manager
            )
            templater.create_all()
            results[player] = templater
        
        self.templates[str(subtitle_path)] = results
        return results
    
    def get_player_command(self, 
                          player: PlayerType,
                          url: str, 
                          subtitle_path: Union[str, Path]) -> str:
        """
        Get the command line for a specific player.
        
        Args:
            player: The player to use
            url: Video URL
            subtitle_path: Subtitle file path
            
        Returns:
            Formatted command string
        """
        config = PlayerConfig.default_configs().get(player)
        if not config:
            raise ValueError(f"No config for player: {player}")
        
        subtitle = Path(subtitle_path)
        cmd = f"{config.executable} '{url}' {config.pause_flag} {config.sub_flag}'{subtitle}'"
        return cmd
    
    def cleanup_all_unfinished(self) -> Dict[str, List[Path]]:
        """
        Clean up all unfinished markers across all templates.
        
        Returns:
            Dictionary mapping template to list of removed files
        """
        results = {}
        for key, templater_dict in self.templates.items():
            for player, templater in templater_dict.items():
                removed = templater.cleanup_unfinished()
                if removed:
                    results[f"{key}_{player.value}"] = removed
        return results


# Convenience functions
def quick_template(url: str, 
                  subtitle: str, 
                  player: str = 'mpv',
                  output_dir: str = '.') -> Dict[str, Path]:
    """
    Quick one-liner to create a template.
    
    Args:
        url: Video URL
        subtitle: Subtitle file path
        player: Player to use ('mpv', 'vlc', 'ffplay', etc.)
        output_dir: Output directory
        
    Returns:
        Dictionary of created files
    """
    templater = MPVTemplater(url, subtitle, output_dir, player=player)
    return templater.create_all()


if __name__ == '__main__':
    # Example usage
    import argparse
    
    parser = argparse.ArgumentParser(description='Create MPV templates with multi-player support')
    parser.add_argument('url', help='Video URL or path')
    parser.add_argument('subtitle', help='Subtitle file path')
    parser.add_argument('-o', '--output', default='.', help='Output directory')
    parser.add_argument('-p', '--player', default='mpv', 
                       choices=['mpv', 'vlc', 'ffplay', 'mplayer', 'celluloid'],
                       help='Media player to use')
    parser.add_argument('--multi', action='store_true', 
                       help='Generate templates for multiple players')
    
    args = parser.parse_args()
    
    if args.multi:
        manager = MultiPlayerManager(args.output)
        results = manager.create_multi_player_templates(args.url, args.subtitle)
        print(f"Generated templates for {len(results)} players")
        for player, templater in results.items():
            print(f"  {player.value}: {len(templater.generated_files)} files")
    else:
        templater = MPVTemplater(args.url, args.subtitle, args.output, player=args.player)
        files = templater.create_all()
        print(f"Generated {len(files)} template files for {args.player}")
        for ftype, fpath in files.items():
            print(f"  {ftype}: {fpath}")