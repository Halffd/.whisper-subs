//! whisper-subs TUI: search the subtitle library, YouTube, and cue text, then
//! play results through mpv.

mod app;
mod config;
mod index;
mod player;
mod srt;
mod youtube;

fn main() -> std::io::Result<()> {
    app::start()
}
