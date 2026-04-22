#!/usr/bin/env python3
"""
Fix run scripts (.sh, .bat) that point to unfinished subtitle files.
Uses fuzzy matching to find correct subtitle files and fixes quote escaping issues.
"""

import os
import sys
import json
import re
import argparse
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from difflib import SequenceMatcher
from glob import glob


def similarity(a: str, b: str) -> float:
    """Calculate string similarity ratio."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def find_subtitle_for_script(script_path: str, subtitle_dir: Optional[str] = None) -> Optional[str]:
    """
    Find the best matching subtitle file for a run script using fuzzy search.
    
    Args:
        script_path: Path to the run script (.sh or .bat)
        subtitle_dir: Directory to search for subtitles (default: same as script)
    
    Returns:
        Path to best matching subtitle file or None
    """
    script_name = Path(script_path).stem
    search_dir = subtitle_dir or os.path.dirname(script_path)
    
    if not os.path.exists(search_dir):
        return None
    
    # Remove common suffixes from script name
    clean_name = re.sub(r'\.(sh|bat)$', '', script_name, flags=re.IGNORECASE)
    clean_name = re.sub(r'\.(unfinished|srt)$', '', clean_name, flags=re.IGNORECASE)
    
    # Find all potential subtitle files
    candidates = []
    for ext in ['.srt', '.unfinished.srt']:
        candidates.extend(glob(os.path.join(search_dir, f'*{ext}')))
    
    best_match = None
    best_score = 0.0
    
    for candidate in candidates:
        candidate_name = Path(candidate).stem
        # Remove .unfinished suffix for comparison
        candidate_clean = re.sub(r'\.unfinished$', '', candidate_name)
        
        score = similarity(clean_name, candidate_clean)
        
        # Boost score if file actually exists
        if os.path.exists(candidate):
            score += 0.1
        
        # Prefer non-unfinished files
        if '.unfinished.' not in candidate:
            score += 0.2
        
        if score > best_score:
            best_score = score
            best_match = candidate
    
    # Only return if similarity is above threshold
    if best_score >= 0.5:
        return best_match
    
    return None


def escape_shell_single_quotes(text: str) -> str:
    """Escape single quotes for shell scripts."""
    return text.replace("'", "'\\''")


def escape_batch_quotes(text: str) -> str:
    """Escape quotes for Windows batch files."""
    # In batch, we need to escape quotes by doubling them or using caret
    # For simplicity, we'll use double quotes where possible
    return text.replace('"', '""')


def fix_script_content(content: str, old_path: str, new_path: str, script_type: str) -> str:
    """
    Fix script content to point to correct subtitle file and fix quote issues.
    
    Args:
        content: Original script content
        old_path: Old subtitle path (with .unfinished)
        new_path: New subtitle path (without .unfinished)
        script_type: 'sh' or 'bat'
    
    Returns:
        Fixed script content
    """
    # First, fix the path replacement
    old_path_normalized = os.path.normpath(old_path)
    new_path_normalized = os.path.normpath(new_path)
    
    # Handle both unfinished and non-unfinished paths
    variations = [
        old_path_normalized,
        old_path_normalized.replace('.unfinished.srt', '.srt'),
        old_path_normalized.replace('.srt', '.unfinished.srt'),
        os.path.basename(old_path_normalized),
        os.path.basename(old_path_normalized).replace('.unfinished.srt', '.srt'),
    ]
    
    fixed_content = content
    
    for old_var in set(variations):
        # Escape for regex
        old_escaped = re.escape(old_var)
        
        # Replace in content
        fixed_content = re.sub(old_escaped, new_path_normalized, fixed_content)
    
    # Fix quote issues based on script type
    if script_type == 'sh':
        # Fix shell script quote issues
        # Pattern: mpv '...' --sub-file='...'
        # Need to ensure proper escaping
        
        # Fix unescaped single quotes within single-quoted strings
        def fix_shell_quotes(match):
            prefix = match.group(1)
            path = match.group(2)
            suffix = match.group(3)
            
            # Escape any single quotes in the path
            escaped_path = escape_shell_single_quotes(path)
            return f"{prefix}'{escaped_path}'{suffix}"
        
        # Match patterns like: --sub-file='...' or just '...'
        fixed_content = re.sub(
            r"(--sub-file=)?'([^']*\.srt[^']*)'(.*)$",
            fix_shell_quotes,
            fixed_content,
            flags=re.MULTILINE
        )
        
    elif script_type == 'bat':
        # Fix batch file quote issues
        # Pattern: mpv "..." --sub-file="..."
        
        def fix_batch_quotes(match):
            prefix = match.group(1)
            path = match.group(2)
            suffix = match.group(3)
            
            # For batch, prefer using double quotes and escaping if needed
            # Actually, for --sub-file=", we can just ensure proper quoting
            if '"' in path:
                path = path.replace('"', '\\"')
            return f'{prefix}"{path}"{suffix}'
        
        fixed_content = re.sub(
            r'(--sub-file=)?"([^"]*\.srt[^"]*)"(.*)$',
            fix_batch_quotes,
            fixed_content,
            flags=re.MULTILINE
        )
    
    return fixed_content


def process_script(script_path: str, dry_run: bool = False) -> Dict:
    """
    Process a single run script file.
    
    Args:
        script_path: Path to the script
        dry_run: If True, don't actually modify files
    
    Returns:
        Dict with status and details
    """
    result = {
        'script': script_path,
        'success': False,
        'action': None,
        'old_subtitle': None,
        'new_subtitle': None,
        'error': None
    }
    
    try:
        # Determine script type
        if script_path.endswith('.sh'):
            script_type = 'sh'
        elif script_path.endswith('.bat'):
            script_type = 'bat'
        else:
            result['error'] = 'Unknown script type (not .sh or .bat)'
            return result
        
        # Read script content
        with open(script_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        result['original_content'] = content
        
        # Find current subtitle path in script
        # Pattern for mpv --sub-file='...' or mpv "..." --sub-file="..."
        subfile_pattern = r'(?:--sub-file[=\s])[\'"]?([^\'"\s]+\.srt(?:\.unfinished)?)[\'"]?(?:\s|$)'
        match = re.search(subfile_pattern, content)
        
        if not match:
            # Try alternative patterns
            subfile_pattern = r'(?:--sub-file[=\s])([\'"])([^\1]+?\.srt[^\1]*)\1'
            match = re.search(subfile_pattern, content)
            if match:
                current_sub = match.group(2)
            else:
                result['error'] = 'No --sub-file found in script'
                return result
        else:
            current_sub = match.group(1)
        
        result['old_subtitle'] = current_sub
        
        # Check if it points to unfinished
        if '.unfinished.srt' not in current_sub:
            result['success'] = True
            result['action'] = 'no_change'
            result['message'] = 'Script already points to finished subtitle'
            return result
        
        # Find correct subtitle file
        new_sub = find_subtitle_for_script(script_path)
        
        if not new_sub:
            result['error'] = 'Could not find matching subtitle file'
            return result
        
        result['new_subtitle'] = new_sub
        
        # Fix the script content
        fixed_content = fix_script_content(content, current_sub, new_sub, script_type)
        
        result['fixed_content'] = fixed_content
        
        if dry_run:
            result['success'] = True
            result['action'] = 'dry_run'
            return result
        
        # Backup original
        backup_path = script_path + '.bak'
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Write fixed content
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
        
        result['success'] = True
        result['action'] = 'fixed'
        result['backup'] = backup_path
        
    except Exception as e:
        result['error'] = str(e)
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description='Fix run scripts that point to unfinished subtitle files'
    )
    parser.add_argument(
        'paths',
        nargs='*',
        help='Paths to run scripts or directories to scan'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without modifying files'
    )
    parser.add_argument(
        '--output',
        '-o',
        default='report.json',
        help='Output report file (default: report.json)'
    )
    parser.add_argument(
        '--recursive',
        '-r',
        action='store_true',
        help='Scan directories recursively'
    )
    parser.add_argument(
        '--min-similarity',
        '-m',
        type=float,
        default=0.5,
        help='Minimum similarity score for matching (0-1, default: 0.5)'
    )
    
    args = parser.parse_args()
    
    # Collect all script files
    script_files = []
    
    for path in args.paths:
        path = os.path.abspath(path)
        
        if os.path.isfile(path):
            if path.endswith(('.sh', '.bat')):
                script_files.append(path)
        elif os.path.isdir(path):
            if args.recursive:
                for root, dirs, files in os.walk(path):
                    for f in files:
                        if f.endswith(('.sh', '.bat')):
                            script_files.append(os.path.join(root, f))
            else:
                for f in os.listdir(path):
                    if f.endswith(('.sh', '.bat')):
                        script_files.append(os.path.join(path, f))
    
    if not script_files:
        print("No script files found.")
        sys.exit(1)
    
    print(f"Found {len(script_files)} script files to process")
    
    # Process each script
    results = []
    fixed_count = 0
    error_count = 0
    unchanged_count = 0
    
    for script_path in script_files:
        print(f"\nProcessing: {script_path}")
        result = process_script(script_path, args.dry_run)
        results.append(result)
        
        if result['success']:
            if result['action'] == 'fixed':
                print(f"  ✓ Fixed: {result['old_subtitle']} → {result['new_subtitle']}")
                fixed_count += 1
            elif result['action'] == 'no_change':
                print(f"  ✓ No change needed: {result.get('message', '')}")
                unchanged_count += 1
            elif result['action'] == 'dry_run':
                print(f"  [DRY RUN] Would fix: {result['old_subtitle']} → {result['new_subtitle']}")
        else:
            print(f"  ✗ Error: {result['error']}")
            error_count += 1
    
    # Generate report
    report = {
        'summary': {
            'total': len(script_files),
            'fixed': fixed_count,
            'unchanged': unchanged_count,
            'errors': error_count,
            'dry_run': args.dry_run
        },
        'results': results
    }
    
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print(f"Summary: {fixed_count} fixed, {unchanged_count} unchanged, {error_count} errors")
    print(f"Report saved to: {args.output}")
    
    if args.dry_run:
        print("\nThis was a dry run. No files were modified.")
        print("Run without --dry-run to apply changes.")


if __name__ == '__main__':
    main()
