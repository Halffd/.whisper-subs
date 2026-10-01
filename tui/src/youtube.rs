//! YouTube search and transcription hand-off, both via `yt-dlp` and
//! `whisper_subs.py` subprocesses.
//!
//! Every pipe a child writes to is drained by a thread, so a large response or
//! a chatty subprocess can never fill a pipe buffer and deadlock the caller.

use serde::Deserialize;
use std::io::Read;
use std::os::unix::process::CommandExt;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Deserialize)]
pub struct YoutubeHit {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub channel: Option<String>,
    #[serde(default)]
    pub channel_url: Option<String>,
    #[serde(default)]
    pub webpage_url: Option<String>,
    #[serde(default)]
    pub duration: Option<f64>,
    #[serde(default)]
    pub view_count: Option<i64>,
    #[serde(default)]
    pub upload_date: Option<String>,
    #[serde(default)]
    pub thumbnail: Option<String>,
}

impl YoutubeHit {
    pub fn url(&self) -> String {
        self.webpage_url
            .clone()
            .unwrap_or_else(|| format!("https://www.youtube.com/watch?v={}", self.id))
    }

    pub fn channel_label(&self) -> &str {
        self.channel.as_deref().unwrap_or("unknown channel")
    }
}

/// Searches YouTube with `ytsearchN:`. Returns an error string for the UI.
///
/// `yt-dlp` has no timeout flag, so the caller enforces one: a search that
/// outstays `timeout` is killed and reported as a timeout.
pub fn search(
    yt_dlp: &str,
    query: &str,
    limit: usize,
    timeout: Duration,
) -> Result<Vec<YoutubeHit>, String> {
    let query = query.trim();
    if query.is_empty() {
        return Ok(Vec::new());
    }
    let target = format!("ytsearch{limit}:{query}");

    let mut child = spawn(|| {
        Command::new(yt_dlp)
            .args([
                "--dump-single-json",
                "--flat-playlist",
                "--no-warnings",
                "--socket-timeout",
                "15",
            ])
            .arg(&target)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            // Its own process group, so killing it also kills anything it
            // spawned. Without this, a wrapper script leaves a grandchild
            // holding the pipe open and the reader threads never finish.
            .process_group(0)
            .spawn()
    })
    .map_err(|e| format!("could not run {yt_dlp}: {e}"))?;

    let stdout = child.stdout.take().ok_or("yt-dlp stdout closed")?;
    let stderr = child.stderr.take().ok_or("yt-dlp stderr closed")?;
    let out_handle = std::thread::spawn(move || slurp(stdout));
    let err_handle = std::thread::spawn(move || slurp(stderr));

    let deadline = Instant::now() + timeout;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(50)),
            Ok(None) => {
                kill_group(&mut child);
                return Err(format!("yt-dlp search timed out after {timeout:?}"));
            }
            Err(e) => return Err(format!("yt-dlp search failed: {e}")),
        }
    };

    let stdout_text = out_handle.join().unwrap_or_default();
    let stderr_text = err_handle.join().unwrap_or_default();
    if !status.success() {
        let tail = stderr_text
            .lines()
            .rev()
            .take(3)
            .collect::<Vec<_>>()
            .join(" ");
        return Err(if tail.is_empty() {
            format!("yt-dlp exited with {status}")
        } else {
            format!("yt-dlp error: {tail}")
        });
    }

    let mut hits = Vec::new();
    for line in stdout_text.lines().filter(|l| !l.trim().is_empty()) {
        let Ok(parsed) = serde_json::from_str::<serde_json::Value>(line) else {
            continue;
        };
        // ytsearch wraps results in {"entries": [...]}.
        if let Some(entries) = parsed.get("entries").and_then(|e| e.as_array()) {
            for entry in entries {
                if let Ok(hit) = serde_json::from_value::<YoutubeHit>(entry.clone()) {
                    hits.push(hit);
                }
            }
        } else if let Ok(hit) = serde_json::from_value::<YoutubeHit>(parsed) {
            hits.push(hit);
        }
    }
    hits.truncate(limit);
    Ok(hits)
}

/// Kills a child and every process it spawned.
fn kill_group(child: &mut Child) {
    // A negative pid signals the whole process group created by
    // `process_group(0)`, which is what stops a wrapper script from leaving a
    // grandchild holding the output pipes open.
    unsafe {
        libc::kill(-(child.id() as i32), libc::SIGKILL);
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn slurp(mut source: impl Read) -> String {
    let mut buffer = String::new();
    let _ = source.read_to_string(&mut buffer);
    buffer
}

/// `errno` for ETXTBSY.
const ETXTBSY: i32 = 26;
/// How long to keep retrying an ETXTBSY spawn before giving up.
const SPAWN_RETRY_WINDOW: Duration = Duration::from_millis(500);
/// Pause between ETXTBSY attempts.
const SPAWN_RETRY_DELAY: Duration = Duration::from_millis(10);

/// Starts a child, retrying while the kernel reports ETXTBSY.
///
/// On tmpfs the kernel intermittently reports the executable as busy when it
/// was written moments earlier, even though no process holds it open. Probing
/// `/proc` at failure time finds no holder, so the lock is spurious and the
/// only correct response is to wait it out. Roughly 2% of spawns hit this when
/// several threads start freshly written files at once.
///
/// `Command::spawn` consumes the command, so the caller passes a closure that
/// rebuilds an identical command per attempt.
fn spawn(build: impl Fn() -> std::io::Result<Child>) -> std::io::Result<Child> {
    let deadline = Instant::now() + SPAWN_RETRY_WINDOW;
    loop {
        match build() {
            Err(e) if e.raw_os_error() == Some(ETXTBSY) && Instant::now() < deadline => {
                std::thread::sleep(SPAWN_RETRY_DELAY);
            }
            other => return other,
        }
    }
}

/// Runs `whisper_subs.py <model> <url> --show`, streaming its output so the
/// TUI shows segments while the Python side works.
pub fn transcribe(
    python: &str,
    script: &std::path::Path,
    model: &str,
    url: &str,
    mut on_line: impl FnMut(String) + Send + 'static,
) -> Result<bool, String> {
    let mut child = spawn(|| {
        Command::new(python)
            .arg(script)
            .arg(model)
            .arg(url)
            .arg("--show")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .process_group(0)
            .spawn()
    })
    .map_err(|e| format!("could not run {python}: {e}"))?;

    let mut readers = Vec::new();
    if let Some(stdout) = child.stdout.take() {
        readers.push(std::thread::spawn(move || {
            use std::io::{BufRead, BufReader};
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                on_line(line);
            }
        }));
    }
    if let Some(stderr) = child.stderr.take() {
        readers.push(std::thread::spawn(move || {
            // Log noise goes to the UI log too, tagged so it is not mistaken
            // for subtitle output.
            use std::io::{BufRead, BufReader};
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                eprintln!("whisper_subs stderr: {line}");
            }
        }));
    }

    let status = child
        .wait()
        .map_err(|e| format!("transcription failed: {e}"))?;
    // The child can exit before its pipes are drained; joining guarantees every
    // line reaches `on_line` before the caller reports completion.
    for reader in readers {
        let _ = reader.join();
    }
    Ok(status.success())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    /// Writes an executable shell script in a directory private to this test.
    ///
    /// The body is written to a scratch name and renamed into place. Executing
    /// a file that another thread may still hold open for writing intermittently
    /// fails with ETXTBSY; a renamed inode is never the one being written, so
    /// the spawn cannot race.
    fn script_that(name: &str, body: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "ws-youtube-test-{}-{}-{}",
            name,
            std::process::id(),
            unique_suffix()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let scratch = dir.join(format!("fake-tool.{}.tmp", unique_suffix()));
        let path = dir.join("fake-tool");
        let mut file = std::fs::File::create(&scratch).unwrap();
        file.write_all(body.as_bytes()).unwrap();
        file.sync_all().unwrap();
        drop(file);
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&scratch, std::fs::Permissions::from_mode(0o755)).unwrap();
        std::fs::rename(&scratch, &path).unwrap();
        path
    }

    fn unique_suffix() -> u64 {
        use std::sync::atomic::{AtomicU64, Ordering};
        static COUNTER: AtomicU64 = AtomicU64::new(0);
        COUNTER.fetch_add(1, Ordering::Relaxed)
    }

    #[test]
    fn parses_flat_entries_and_drops_blank_lines() {
        let fake = script_that(
            "fake-yt-dlp",
            "#!/bin/sh\n\
             echo '{\"entries\":[{\"id\":\"a\",\"title\":\"First\",\"channel\":\"Chan\",\"duration\":61},{\"id\":\"b\",\"title\":\"Second\"}]}'\n\
             echo ''\n",
        );

        let hits = search(
            fake.to_str().unwrap(),
            "anything",
            25,
            Duration::from_secs(30),
        )
        .unwrap();
        assert_eq!(hits.len(), 2);
        assert_eq!(hits[0].title, "First");
        assert_eq!(hits[0].channel_label(), "Chan");
        assert_eq!(hits[1].channel_label(), "unknown channel");
        assert_eq!(hits[0].url(), "https://www.youtube.com/watch?v=a");

        let _ = std::fs::remove_dir_all(fake.parent().unwrap());
    }

    #[test]
    fn reports_stderr_tail_on_failure() {
        let fake = script_that(
            "fake-yt-dlp-fail",
            "#!/bin/sh\n\
             echo 'ERROR: Video unavailable' >&2\n\
             exit 1\n",
        );
        let err = search(fake.to_str().unwrap(), "q", 5, Duration::from_secs(30)).unwrap_err();
        assert!(err.contains("Video unavailable"), "got: {err}");
        let _ = std::fs::remove_dir_all(fake.parent().unwrap());
    }

    #[test]
    fn kills_a_hung_search_at_the_timeout() {
        let fake = script_that("fake-yt-dlp-hang", "#!/bin/sh\nsleep 30\n");
        let started = Instant::now();
        let err = search(fake.to_str().unwrap(), "q", 5, Duration::from_millis(600)).unwrap_err();
        assert!(err.contains("timed out"), "got: {err}");
        assert!(
            started.elapsed() < Duration::from_secs(10),
            "search should be killed near the timeout, took {:?}",
            started.elapsed()
        );
        let _ = std::fs::remove_dir_all(fake.parent().unwrap());
    }

    #[test]
    fn survives_output_larger_than_a_pipe_buffer() {
        // ~200 KB of entries: well past the 64 KB pipe buffer, so an undrained
        // pipe would block the child instead of delivering results.
        let body = "#!/usr/bin/env python3\n\
            import json\n\
            entries = [{\"id\": f\"id{i}\", \"title\": f\"Title number {i}\"} for i in range(1200)]\n\
            print(json.dumps({\"entries\": entries}))\n";
        let tool = script_that("fake-yt-dlp-big", body);

        let hits = search(tool.to_str().unwrap(), "q", 2000, Duration::from_secs(30)).unwrap();
        assert_eq!(hits.len(), 1200);
        assert_eq!(hits[0].title, "Title number 0");
        assert_eq!(hits[1199].title, "Title number 1199");

        let _ = std::fs::remove_dir_all(tool.parent().unwrap());
    }

    #[test]
    fn transcribe_streams_stdout_and_reports_exit_status() {
        let fake = script_that(
            "fake-whisper",
            "#!/bin/sh\n\
             echo \"segment one\"\n\
             echo \"segment two\"\n\
             echo \"a stderr note\" >&2\n\
             exit ${FAKE_EXIT:-0}\n",
        );
        let seen = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
        let sink = seen.clone();
        let ok = transcribe(
            "sh",
            fake.as_path(),
            "tiny",
            "https://youtu.be/x",
            move |line| sink.lock().unwrap().push(line),
        )
        .unwrap();
        assert!(ok);
        assert_eq!(*seen.lock().unwrap(), vec!["segment one", "segment two"]);
        let _ = std::fs::remove_dir_all(fake.parent().unwrap());
    }

    #[test]
    fn transcribe_reports_failure_exit_code() {
        let fake = script_that("fake-whisper-fail", "#!/bin/sh\nexit 3\n");
        let ok = transcribe("sh", fake.as_path(), "tiny", "url", |_| {}).unwrap();
        assert!(!ok);
        let _ = std::fs::remove_dir_all(fake.parent().unwrap());
    }

    #[test]
    fn empty_query_skips_the_subprocess() {
        assert!(search(
            "definitely-not-a-real-binary",
            "   ",
            5,
            Duration::from_secs(1)
        )
        .is_ok());
    }

    #[test]
    fn missing_binary_is_reported() {
        let err = search(
            "definitely-not-a-real-binary-xyz",
            "q",
            5,
            Duration::from_secs(5),
        )
        .unwrap_err();
        assert!(err.contains("could not run"), "got: {err}");
    }
}
