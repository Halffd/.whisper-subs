import os
import subprocess
import requests
import json
from dotenv import load_dotenv
from pathlib import Path
import time
from datetime import datetime

load_dotenv()

class StreamlinkVODDownloader:
    def get_app_access_token(self):
        """Get a new app access token"""
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            'client_id': self.client_id,
            'client_secret': os.getenv('TWITCH_CLIENT_SECRET'),  # You'll need this
            'grant_type': 'client_credentials'
        }
        
        response = requests.post(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            return data['access_token']
        else:
            print(f"Token generation failed: {response.text}")
            return None

    def __init__(self):
        self.client_id = os.getenv('TWITCH_CLIENT_ID')
        self.client_secret = os.getenv('TWITCH_CLIENT_SECRET')
        self.output_dir = os.getenv('OUTPUT_DIR', 'downloads')
        self.audio_quality = os.getenv('AUDIO_QUALITY', '128k')
        
        if not self.client_id or not self.client_secret:
            raise ValueError("Missing Twitch credentials in .env file")
        
        # Get fresh token
        self.access_token = self.get_app_access_token()
        if not self.access_token:
            raise ValueError("Failed to get access token")
            
        self.headers = {
            'Client-ID': self.client_id,
            'Authorization': f'Bearer {self.access_token}'
        }
        
        Path(self.output_dir).mkdir(exist_ok=True)
    def get_user_id(self, username):
        """Get user ID from username - original method, keeping for compatibility"""
        url = f"https://api.twitch.tv/helix/users?login={username}"
        response = requests.get(url, headers=self.headers)
        
        if response.status_code != 200:
            print(f"API Error: {response.status_code} - {response.text}")
            return None
            
        data = response.json()
        return data['data'][0]['id'] if data['data'] else None

    def get_user_id_by_login(self, login_name):
        """Get user_id from channel login name"""
        params = {'login': login_name}
        response = requests.get('https://api.twitch.tv/helix/users', 
                              headers=self.headers, params=params)
        
        if response.status_code == 200:
            data = response.json()
            if data['data']:
                return data['data'][0]['id']
            else:
                return None  # User not found
        else:
            print(f"API Error: {response.status_code} - {response.text}")
            return None

    def get_all_vods(self, user_id, limit=None):
        """Get all available VODs for a user"""
        url = f"https://api.twitch.tv/helix/videos?user_id={user_id}&type=archive"
        all_vods = []
        cursor = None
        
        while True:
            params = {'first': 20}
            if cursor:
                params['after'] = cursor
                
            response = requests.get(url, headers=self.headers, params=params)
            
            if response.status_code != 200:
                print(f"API Error: {response.status_code}")
                break
                
            data = response.json()
            
            if not data.get('data'):
                break
                
            all_vods.extend(data['data'])
            
            if limit and len(all_vods) >= limit:
                all_vods = all_vods[:limit]
                break
                
            cursor = data.get('pagination', {}).get('cursor')
            
            if not cursor:
                break
                
        return all_vods
    
    def sanitize_filename(self, filename):
        """Clean filename for filesystem"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename[:200]  # Limit length
    
    def download_vod_audio(self, vod_id, title, duration):
        """Download VOD audio using streamlink"""
        safe_title = self.sanitize_filename(title)
        temp_file = f"{self.output_dir}/{vod_id}_{safe_title}.ts"
        final_file = f"{self.output_dir}/{vod_id}_{safe_title}.mp3"
        
        # Check if already downloaded
        if os.path.exists(final_file):
            print(f"Already exists: {safe_title}")
            return True
        
        print(f"Downloading: {safe_title} ({duration})")
        
        try:
            # Download with streamlink
            streamlink_cmd = [
                'streamlink',
                f'https://www.twitch.tv/videos/{vod_id}',
                'audio',
                '--output', final_file,
                '--twitch-disable-ads',
                '--retry-streams', '3',
                '--retry-max', '5'
            ]
            
            result = subprocess.run(
                streamlink_cmd, 
                capture_output=True, 
                text=True,
                timeout=3600  # 1 hour timeout
            )
            
            if result.returncode != 0:
                print(f"Streamlink failed for {vod_id}: {result.stderr}")
                return False
            
            print(f"✓ Completed: {safe_title}")
            return True
            
        except subprocess.TimeoutExpired:
            print(f"Timeout downloading {vod_id}")
            return False
        except Exception as e:
            print(f"Error downloading {vod_id}: {e}")
            return False
    
    def download_channel_vods(self, username, limit=None, skip_existing=True):
        """Download all VODs from a channel"""
        print(f"Getting VODs for {username}...")
        
        user_id = self.get_user_id_by_login(username)  # Fixed: removed extra argument
        if not user_id:
            print(f"User {username} not found")
            return
        
        vods = self.get_all_vods(user_id, limit)
        print(f"Found {len(vods)} VODs")
        
        if not vods:
            print("No VODs found")
            return
        
        success_count = 0
        failed_count = 0
        
        for i, vod in enumerate(vods, 1):
            print(f"\n[{i}/{len(vods)}] Processing VOD {vod['id']}")
            
            success = self.download_vod_audio(
                vod['id'], 
                vod['title'], 
                vod['duration']
            )
            
            if success:
                success_count += 1
            else:
                failed_count += 1
            
            # Be nice to Twitch's servers
            time.sleep(2)
        
        print(f"\n=== Summary ===")
        print(f"Success: {success_count}")
        print(f"Failed: {failed_count}")
        print(f"Total: {len(vods)}")

def main():
    downloader = StreamlinkVODDownloader()
    
    # Example usage
    channel = input("Enter channel name: ").strip()
    limit = input("Limit number of VODs (press enter for all): ").strip()
    
    limit = int(limit) if limit.isdigit() else None
    
    downloader.download_channel_vods(channel, limit)

if __name__ == "__main__":
    main()