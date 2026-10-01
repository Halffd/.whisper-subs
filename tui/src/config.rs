//! Configuration and library paths.
//!
//! Every default is overridable in `~/.config/WhisperSubs/tui.toml`, which is
//! the same directory the Python side already uses for `jobs.json`.

use serde::Deserialize;
use std::path::{Path, PathBuf};

#[derive(Debug, Deserialize)]
#[serde(default)]
pub struct Config {
    /// Root of the subtitle/media library produced by whisper_subs.py.
    pub library_dir: PathBuf,
    /// Where the SQLite index lives.
    pub cache_dir: PathBuf,
    /// Socket used for the embedded mpv player.
    pub mpv_socket: String,
    /// Socket the Python side uses when it launches mpv itself (--mpv).
    pub whisper_mpv_socket: String,
    /// `yt-dlp` executable used for YouTube search.
    pub yt_dlp: String,
    /// `whisper_subs.py` used to transcribe a YouTube search hit.
    pub whisper_subs: PathBuf,
    /// Python interpreter for the transcription command.
    pub python: String,
    /// Models offered for transcription, in menu order.
    pub models: Vec<String>,
    /// Job history written by whisper_subs.py.
    pub jobs_file: PathBuf,
}

impl Default for Config {
    fn default() -> Self {
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("/tmp"));
        Self {
            library_dir: home.join("Documents/Youtube-Subs"),
            cache_dir: home.join(".cache/whisper-subs"),
            mpv_socket: "/tmp/whisper-subs-tui-mpvsocket".into(),
            whisper_mpv_socket: "/tmp/mpvsocket".into(),
            yt_dlp: "yt-dlp".into(),
            whisper_subs: repo_root().join("whisper_subs.py"),
            python: "python3".into(),
            models: vec!["tiny.en".into(), "base.en".into(), "medium.en".into()],
            jobs_file: config_dir().join("jobs.json"),
        }
    }
}

/// The repository this crate was built from, so `whisper_subs.py` resolves
/// no matter which directory the TUI was started in.
fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .to_path_buf()
}

impl Config {
    /// Loads `tui.toml` when present, otherwise returns defaults.
    pub fn load() -> Self {
        let mut config = Config::default();
        let path = config_dir().join("tui.toml");
        let Ok(text) = std::fs::read_to_string(&path) else {
            return config;
        };
        match toml::from_str::<Config>(&text) {
            Ok(parsed) => config = parsed,
            Err(e) => eprintln!("warning: ignoring {}: {e}", path.display()),
        }
        config
    }

    pub fn index_path(&self) -> PathBuf {
        self.cache_dir.join("tui-index.sqlite")
    }

    /// Subtitle and metadata pairs produced next to the media.
    pub fn library_dir(&self) -> &Path {
        &self.library_dir
    }

    pub fn jobs_file(&self) -> &Path {
        &self.jobs_file
    }

    /// The script to hand to Python. A configured relative path is resolved
    /// against this crate's repository when it does not exist in the current
    /// directory, so the TUI works from any working directory.
    pub fn whisper_subs_script(&self) -> PathBuf {
        if self.whisper_subs.is_absolute() || self.whisper_subs.exists() {
            return self.whisper_subs.clone();
        }
        let candidate = repo_root().join("whisper_subs.py");
        if candidate.exists() {
            candidate
        } else {
            self.whisper_subs.clone()
        }
    }
}

pub fn config_dir() -> PathBuf {
    let home = std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/tmp"));
    home.join(".config/WhisperSubs")
}
