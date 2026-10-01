//! mpv player over JSON IPC.
//!
//! The TUI owns the mpv process: it starts one per playback with an IPC
//! socket, then sends commands and reads property changes over that socket.
//! Replies and events share one stream, so every read is matched against the
//! `request_id` that was sent; anything else is an event to fold into state.

use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;

/// How long a single socket read waits for a line before giving up. mpv pushes
/// `time-pos` constantly, so this is only reached when the stream is idle.
const READ_TIMEOUT: Duration = Duration::from_millis(50);
/// How long `poll` keeps draining before handing control back to the UI. Without
/// this bound, a playing file would keep `poll` busy for its whole duration.
const POLL_WINDOW: Duration = Duration::from_millis(100);
/// How long a command may take to be answered in total, however many idle reads
/// that spans.
const COMMAND_TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Clone, Copy, Debug)]
pub struct PlaybackState {
    pub position: Duration,
    pub duration: Option<Duration>,
    pub paused: bool,
}

pub struct Player {
    writer: UnixStream,
    reader: BufReader<UnixStream>,
    next_id: u64,
    position: Duration,
    duration: Option<Duration>,
    paused: bool,
    connected: bool,
    /// Set when a message read inside `command` changed state, so the next
    /// `poll` reports it. Reply waiting consumes events that `poll` would
    /// otherwise have surfaced.
    pending: bool,
}

impl Player {
    /// Connects to a running mpv and starts observing the properties the UI
    /// displays.
    pub fn connect(socket: &str) -> Result<Self, String> {
        let stream = UnixStream::connect(socket)
            .map_err(|e| format!("cannot reach mpv at {socket}: {e}"))?;
        let writer = stream
            .try_clone()
            .map_err(|e| format!("mpv socket error: {e}"))?;
        stream
            .set_read_timeout(Some(READ_TIMEOUT))
            .map_err(|e| format!("mpv socket error: {e}"))?;
        let mut player = Player {
            writer,
            reader: BufReader::new(stream),
            next_id: 0,
            position: Duration::ZERO,
            duration: None,
            paused: false,
            connected: true,
            pending: false,
        };
        for (id, name) in [(1, "time-pos"), (2, "duration"), (3, "pause")] {
            player
                .request("observe_property", vec![json!(id), json!(name)])
                .map_err(|e| format!("mpv would not observe {name}: {e}"))?;
        }
        Ok(player)
    }

    /// Retries `connect` while mpv is still starting up.
    pub fn connect_within(socket: &str, timeout: Duration) -> Result<Self, String> {
        let deadline = std::time::Instant::now() + timeout;
        loop {
            match Self::connect(socket) {
                Ok(player) => return Ok(player),
                Err(e) if std::time::Instant::now() < deadline => {
                    let _ = &e;
                    std::thread::sleep(Duration::from_millis(100));
                }
                Err(e) => return Err(e),
            }
        }
    }

    pub fn is_connected(&self) -> bool {
        self.connected
    }

    pub fn seek(&mut self, position: Duration) -> Result<(), String> {
        self.request(
            "seek",
            vec![
                json!(position.as_secs_f64()),
                json!("absolute"),
                json!("exact"),
            ],
        )
    }

    pub fn toggle_pause(&mut self) -> Result<(), String> {
        // Read mpv's own value rather than flipping a local guess: playback can
        // end or be changed from outside, and a stale guess would send two
        // presses in the same direction.
        let paused = !self.is_paused()?;
        self.request("set_property", vec![json!("pause"), json!(paused)])
    }

    /// Asks mpv for the current `pause` flag over IPC.
    pub fn is_paused(&mut self) -> Result<bool, String> {
        let reply = self.command("get_property", vec![json!("pause")])?;
        Ok(reply
            .get("data")
            .and_then(Value::as_bool)
            .unwrap_or(self.paused))
    }

    /// Drains pending events, updating cached position, duration, and pause
    /// state. Returns the new state only when something actually changed.
    pub fn poll(&mut self) -> Option<PlaybackState> {
        let mut changed = self.pending;
        self.pending = false;
        let deadline = std::time::Instant::now() + POLL_WINDOW;
        while std::time::Instant::now() < deadline {
            match self.read_line() {
                Ok(value) => changed |= self.absorb(&value),
                Err(ReadError::Closed) => {
                    self.connected = false;
                    break;
                }
                Err(ReadError::Timeout) => break,
                Err(ReadError::Malformed) => continue,
            }
        }
        if changed {
            Some(PlaybackState {
                position: self.position,
                duration: self.duration,
                paused: self.paused,
            })
        } else {
            None
        }
    }

    /// Asks mpv to quit, so its window closes with the TUI.
    pub fn quit(&mut self) -> Result<(), String> {
        self.request("quit", vec![])
    }

    /// Folds one message into player state. Returns whether state changed.
    fn absorb(&mut self, value: &Value) -> bool {
        if value.get("event").and_then(Value::as_str) == Some("property-change") {
            let name = value.get("name").and_then(Value::as_str).unwrap_or("");
            let data = value.get("data");
            return match name {
                "time-pos" => match data.and_then(Value::as_f64) {
                    Some(secs) if secs >= 0.0 => {
                        let position = Duration::from_secs_f64(secs);
                        let changed = position != self.position;
                        self.position = position;
                        changed
                    }
                    _ => false,
                },
                "duration" => {
                    let duration = data
                        .and_then(Value::as_f64)
                        .filter(|d| *d > 0.0)
                        .map(Duration::from_secs_f64);
                    let changed = duration != self.duration;
                    self.duration = duration;
                    changed
                }
                "pause" => {
                    let paused = data.and_then(Value::as_bool).unwrap_or(false);
                    let changed = paused != self.paused;
                    self.paused = paused;
                    changed
                }
                _ => false,
            };
        }
        match value.get("event").and_then(Value::as_str) {
            Some("end-file") => {
                // `--keep-open` holds the last frame, so park at the end.
                if let Some(duration) = self.duration {
                    self.position = duration;
                }
                self.paused = true;
                true
            }
            Some("shutdown") => {
                self.connected = false;
                false
            }
            _ => false,
        }
    }

    fn request(&mut self, command: &str, args: Vec<Value>) -> Result<(), String> {
        self.command(command, args).map(|_| ())
    }

    /// Sends a command with its arguments inline in the `command` array,
    /// which is the form mpv accepts; a separate `arguments` key is rejected
    /// as an invalid parameter.
    fn command(&mut self, command: &str, args: Vec<Value>) -> Result<Value, String> {
        if !self.connected {
            return Err("mpv connection closed".into());
        }
        self.next_id += 1;
        let request_id = self.next_id;
        let mut call = vec![json!(command)];
        call.extend(args);
        let payload = json!({
            "command": call,
            "request_id": request_id,
        });
        let mut encoded = payload.to_string();
        encoded.push('\n');
        if std::env::var_os("MPV_TRACE").is_some() {
            eprintln!("mpv -> {}", encoded.trim_end());
        }
        self.writer
            .write_all(encoded.as_bytes())
            .map_err(|e| format!("mpv write failed: {e}"))?;

        let deadline = std::time::Instant::now() + COMMAND_TIMEOUT;
        loop {
            match self.read_line() {
                Ok(value) => {
                    if value.get("request_id").and_then(Value::as_u64) != Some(request_id) {
                        // An event arrived before the reply; keep it for state.
                        self.pending |= self.absorb(&value);
                        continue;
                    }
                    if let Some(error) = value.get("error").and_then(Value::as_str) {
                        if error != "success" {
                            return Err(format!("mpv {command}: {error}"));
                        }
                    }
                    return Ok(value);
                }
                Err(ReadError::Closed) => {
                    self.connected = false;
                    return Err("mpv closed the connection".into());
                }
                Err(ReadError::Timeout) => {
                    // An idle read is not a failed command; only the overall
                    // deadline is.
                    if std::time::Instant::now() >= deadline {
                        return Err(format!("mpv did not answer {command} in time"));
                    }
                }
                Err(ReadError::Malformed) => continue,
            }
        }
    }

    fn read_line(&mut self) -> Result<Value, ReadError> {
        let mut line = String::new();
        match self.reader.read_line(&mut line) {
            Ok(0) => Err(ReadError::Closed),
            Ok(_) => {
                if std::env::var_os("MPV_TRACE").is_some() {
                    eprintln!("mpv <- {}", line.trim_end());
                }
                serde_json::from_str(&line).map_err(|_| ReadError::Malformed)
            }
            Err(e)
                if e.kind() == std::io::ErrorKind::WouldBlock
                    || e.kind() == std::io::ErrorKind::TimedOut =>
            {
                Err(ReadError::Timeout)
            }
            Err(_) => Err(ReadError::Closed),
        }
    }
}

enum ReadError {
    Closed,
    Timeout,
    Malformed,
}

/// Starts an mpv window for one playback and returns its process.
///
/// A video window is opened next to the TUI (mpv cannot draw inside a
/// terminal), with the subtitle attached and playback parked at `start`.
pub fn spawn_mpv(
    socket: &str,
    media: &Path,
    subtitle: Option<&Path>,
    start: Duration,
) -> Result<std::process::Child, String> {
    // mpv refuses to bind a socket path that already exists.
    let _ = std::fs::remove_file(socket);
    let mut cmd = std::process::Command::new("mpv");
    cmd.args(["--really-quiet", "--no-terminal"]);
    cmd.args(["--keep-open=yes", "--idle=yes", "--force-window=yes"]);
    cmd.arg(format!("--input-ipc-server={socket}"));
    if let Some(sub) = subtitle {
        if sub.exists() {
            cmd.arg("--sub-file").arg(sub);
        }
    }
    cmd.arg(format!("--start={:.3}", start.as_secs_f64()));
    cmd.arg(media);
    // mpv shares the TUI's terminal; anything it prints there would corrupt
    // the display, and an inherited pipe would let a stray mpv outlive us.
    cmd.stdout(std::process::Stdio::null());
    cmd.stderr(std::process::Stdio::null());
    cmd.stdin(std::process::Stdio::null());
    cmd.spawn().map_err(|e| format!("could not start mpv: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `secs` seconds of silence as an 8 kHz mono WAV, so tests need no media
    /// files. Long enough that playback never reaches EOF mid-assertion.
    fn silent_wav(path: &Path, secs: u32) {
        let samples = 8_000usize * secs as usize;
        let data_len = samples * 2;
        let mut bytes: Vec<u8> = Vec::new();
        bytes.extend_from_slice(b"RIFF");
        bytes.extend_from_slice(&(36u32 + data_len as u32).to_le_bytes());
        bytes.extend_from_slice(b"WAVEfmt ");
        bytes.extend_from_slice(&16u32.to_le_bytes()); // fmt chunk size
        bytes.extend_from_slice(&1u16.to_le_bytes()); // PCM
        bytes.extend_from_slice(&1u16.to_le_bytes()); // mono
        bytes.extend_from_slice(&8_000u32.to_le_bytes()); // sample rate
        bytes.extend_from_slice(&16_000u32.to_le_bytes()); // byte rate
        bytes.extend_from_slice(&2u16.to_le_bytes()); // block align
        bytes.extend_from_slice(&16u16.to_le_bytes()); // bits per sample
        bytes.extend_from_slice(b"data");
        bytes.extend_from_slice(&(data_len as u32).to_le_bytes());
        bytes.resize(bytes.len() + data_len, 0); // silence
        std::fs::write(path, bytes).unwrap();
    }

    fn mpv_available() -> bool {
        std::process::Command::new("mpv")
            .arg("--version")
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
    }

    /// Kills the mpv process when the test unwinds, so a failed assertion
    /// never leaves a window (or an IPC socket) behind.
    struct KillOnDrop(std::process::Child);

    impl Drop for KillOnDrop {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }

    /// Polls until `ready` accepts the newest observed state, or the deadline
    /// passes. Returns the last observed state.
    fn wait_for_state(
        player: &mut Player,
        window: Duration,
        ready: impl Fn(&PlaybackState) -> bool,
    ) -> Option<PlaybackState> {
        let deadline = std::time::Instant::now() + window;
        let mut latest = None;
        while std::time::Instant::now() < deadline {
            if let Some(state) = player.poll() {
                latest = Some(state);
                if ready(&state) {
                    return Some(state);
                }
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        latest
    }

    #[test]
    fn drives_a_real_mpv_instance() {
        if !mpv_available() {
            eprintln!("mpv not installed; skipping player integration test");
            return;
        }
        // A unique directory per run: mpv refuses to bind a socket path that
        // exists, so a shared path would let a stray mpv from an earlier run
        // answer this run's commands.
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir =
            std::env::temp_dir().join(format!("ws-player-test-{}-{stamp}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let media = dir.join("tone.wav");
        silent_wav(&media, 30);
        let socket = dir.join("mpvsock").to_string_lossy().to_string();

        let child = spawn_mpv(&socket, &media, None, Duration::ZERO).unwrap();
        let mut child = KillOnDrop(child);
        let mut player = match Player::connect_within(&socket, Duration::from_secs(5)) {
            Ok(player) => player,
            Err(e) => panic!("could not connect to mpv: {e}"),
        };

        // Playing advances the reported position.
        let advanced = wait_for_state(&mut player, Duration::from_secs(5), |s| {
            s.position > Duration::from_millis(100)
        });
        assert!(
            advanced
                .as_ref()
                .map(|s| s.position > Duration::from_millis(100))
                .unwrap_or(false),
            "time-pos should advance during playback"
        );

        // Pausing is observed, and the position stops moving while paused.
        player.toggle_pause().unwrap();
        let paused = wait_for_state(&mut player, Duration::from_secs(5), |s| s.paused);
        assert!(
            paused.map(|s| s.paused).unwrap_or(false),
            "pause should be observed as true"
        );

        // Seeking while paused moves the position to the requested offset.
        player.seek(Duration::from_secs(10)).unwrap();
        let seeked = wait_for_state(&mut player, Duration::from_secs(5), |s| {
            s.position.abs_diff(Duration::from_secs(10)) < Duration::from_millis(500)
        });
        assert!(
            seeked
                .as_ref()
                .map(|s| s.position.abs_diff(Duration::from_secs(10)) < Duration::from_millis(500))
                .unwrap_or(false),
            "seek should land near 10s, got {:?}",
            seeked.map(|s| s.position)
        );

        // Resuming clears the pause flag.
        player.toggle_pause().unwrap();
        let resumed = wait_for_state(&mut player, Duration::from_secs(5), |s| !s.paused);
        assert!(
            resumed.map(|s| !s.paused).unwrap_or(false),
            "resume should be observed as false"
        );

        let _ = player.quit();
        let _ = child.0.wait();
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn absorbs_property_events() {
        let mut player = Player {
            writer: UnixStream::pair().unwrap().0,
            reader: BufReader::new(UnixStream::pair().unwrap().0),
            next_id: 0,
            position: Duration::ZERO,
            duration: None,
            paused: false,
            connected: true,
            pending: false,
        };
        let changed =
            player.absorb(&json!({"event":"property-change","name":"time-pos","data":12.5}));
        assert!(changed);
        assert_eq!(player.position, Duration::from_millis(12_500));

        assert!(player.absorb(&json!({"event":"property-change","name":"pause","data":true})));
        assert!(player.paused);

        assert!(player.absorb(&json!({"event":"property-change","name":"duration","data":30.0})));
        assert_eq!(player.duration, Some(Duration::from_secs(30)));

        player.absorb(&json!({"event":"end-file","reason":"eof"}));
        assert_eq!(player.position, Duration::from_secs(30));

        player.absorb(&json!({"event":"shutdown"}));
        assert!(!player.is_connected());
    }
}
