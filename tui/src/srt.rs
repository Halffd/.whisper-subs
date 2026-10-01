//! SRT parsing and time formatting.

use std::path::Path;
use std::time::Duration;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Cue {
    pub index: usize,
    pub start: Duration,
    pub end: Duration,
    pub text: String,
}

/// Parses an SRT file. Returns an empty vector for missing or malformed input.
///
/// Tolerates the usual breakage: BOM, CRLF, missing blank separators, and
/// timestamps with a `.` decimal separator instead of `,`.
pub fn parse_srt(path: &Path) -> Vec<Cue> {
    let Ok(raw) = std::fs::read_to_string(path) else {
        return Vec::new();
    };
    parse_srt_str(&raw)
}

pub fn parse_srt_str(raw: &str) -> Vec<Cue> {
    let cleaned = raw.trim_start_matches('\u{feff}').replace("\r\n", "\n");
    let mut cues = Vec::new();

    for block in cleaned.split("\n\n") {
        let mut lines = block.lines().map(str::trim).filter(|l| !l.is_empty());
        let Some(first) = lines.next() else { continue };

        // A leading index number is optional.
        let (index, arrow) = match first.parse::<usize>() {
            Ok(n) => (n, lines.next()),
            Err(_) => (cues.len() + 1, Some(first)),
        };
        let Some(arrow_line) = arrow else { continue };
        if !arrow_line.contains("-->") {
            continue;
        }

        let Some((start, end)) = parse_timestamps(arrow_line) else {
            continue;
        };
        let text = lines.collect::<Vec<_>>().join(" ");
        if text.is_empty() {
            continue;
        }
        cues.push(Cue {
            index,
            start,
            end,
            text,
        });
    }

    cues
}

/// Parses `00:01:02,345 --> 00:01:04,000` into durations.
pub fn parse_timestamps(line: &str) -> Option<(Duration, Duration)> {
    let (left, right) = line.split_once("-->")?;
    Some((parse_timestamp(left)?, parse_timestamp(right)?))
}

fn parse_timestamp(raw: &str) -> Option<Duration> {
    let cleaned = raw.trim().replace(',', ".");
    let mut parts = cleaned.split(':');
    let seconds = parts.next_back()?;
    let minutes = parts.next_back().unwrap_or("0");
    let hours = parts.next_back().unwrap_or("0");
    if parts.next().is_some() {
        return None;
    }
    let seconds: f64 = seconds.parse().ok()?;
    let minutes: u64 = minutes.parse().ok()?;
    let hours: u64 = hours.parse().ok()?;
    Some(Duration::from_secs(hours * 3600 + minutes * 60) + Duration::from_secs_f64(seconds))
}

/// `1:02:03`, compact enough for a table cell.
pub fn format_clock(d: Duration) -> String {
    let total = d.as_secs();
    format!(
        "{}:{:02}:{:02}",
        total / 3600,
        (total / 60) % 60,
        total % 60
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = "\u{feff}1\r\n00:00:01,000 --> 00:00:04,500\r\nHello world\r\n\r\n2\r\n00:01:02,345 --> 00:01:04.000\r\nNão, más\r\n\r\n";

    #[test]
    fn parses_crlf_and_bom() {
        let cues = parse_srt_str(SAMPLE);
        assert_eq!(cues.len(), 2);
        assert_eq!(cues[0].text, "Hello world");
        assert_eq!(cues[0].start, Duration::from_millis(1000));
        assert_eq!(cues[1].text, "Não, más");
        assert_eq!(cues[1].end, Duration::from_millis(64_000));
    }

    #[test]
    fn parses_both_decimal_separators() {
        let (start, end) = parse_timestamps("00:01:02,345 --> 00:01:04.000").unwrap();
        assert_eq!(start, Duration::from_millis(62_345));
        assert_eq!(end, Duration::from_millis(64_000));
    }

    #[test]
    fn rejects_lines_without_a_timestamp() {
        assert!(parse_timestamps("no arrow here").is_none());
    }

    #[test]
    fn missing_index_still_parses() {
        let cues = parse_srt_str("00:00:00,000 --> 00:00:02,000\nno index here");
        assert_eq!(cues.len(), 1);
        assert_eq!(cues[0].index, 1);
    }
}
