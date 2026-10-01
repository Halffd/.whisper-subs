//! SQLite index over the subtitle library and the Python job history.
//!
//! The Python side writes `<name>.srt`, `<name>.metadata.json` and helper
//! files (`.sh`, `.bat`, `.htm`) next to the media. This walks the library
//! once, stores one row per subtitle plus one row per cue, and keeps them in
//! sync using mtime, so repeated launches are cheap.

use crate::config::Config;
use crate::srt::{self, Cue};
use rusqlite::{params, Connection, OptionalExtension};
use serde::Deserialize;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime};

/// Columns of `videos`, in the order every query must select them.
const VIDEO_COLUMNS: &str = "id, srt_path, media_path, title, channel, source_url, channel_url, \
     duration_seconds, views, likes, comments, upload_timestamp, transcription_timestamp, \
     has_human_subs, has_automatic_subs, model, language, segments_count, version, commit_hash, \
     cue_count, srt_mtime";

#[derive(Debug, Clone)]
pub struct Video {
    pub id: i64,
    pub srt_path: PathBuf,
    pub media_path: Option<PathBuf>,
    pub title: String,
    pub channel: Option<String>,
    pub source_url: Option<String>,
    pub channel_url: Option<String>,
    pub duration_seconds: Option<f64>,
    pub views: Option<i64>,
    pub likes: Option<i64>,
    pub comments: Option<i64>,
    pub upload_timestamp: Option<String>,
    pub transcription_timestamp: Option<String>,
    pub has_human_subs: Option<bool>,
    pub has_automatic_subs: Option<bool>,
    pub model: Option<String>,
    pub language: Option<String>,
    pub segments_count: Option<i64>,
    pub version: Option<String>,
    pub commit_hash: Option<String>,
    pub cue_count: i64,
    pub srt_mtime: Option<i64>,
}

#[derive(Debug, Clone)]
pub struct CueHit {
    pub video_id: i64,
    pub cue_index: i64,
    pub start_seconds: f64,
    pub end_seconds: f64,
    pub text: String,
}

/// One entry of `~/.config/WhisperSubs/jobs.json`: a transcription run and
/// the sources it covers.
#[derive(Debug, Clone)]
pub struct Job {
    pub id: i64,
    pub date: Option<String>,
    pub model: Option<String>,
    pub source: String,
    pub status: String,
    pub task_total: i64,
    pub task_done: i64,
    pub task_titles: Vec<String>,
}

impl Job {
    pub fn progress_label(&self) -> String {
        if self.task_total == 0 {
            return "-".into();
        }
        format!("{}/{}", self.task_done, self.task_total)
    }
}

impl Video {
    pub fn channel_label(&self) -> &str {
        self.channel.as_deref().unwrap_or("unknown channel")
    }

    pub fn display_title(&self) -> &str {
        &self.title
    }
}

pub struct Index {
    conn: Connection,
    fts: bool,
}

impl Index {
    pub fn open(config: &Config) -> rusqlite::Result<Self> {
        if let Some(parent) = config.index_path().parent() {
            std::fs::create_dir_all(parent).ok();
        }
        let mut conn = Connection::open(config.index_path())?;
        conn.pragma_update(None, "foreign_keys", "ON")?;
        let fts = Self::migrate(&mut conn)?;
        Ok(Self { conn, fts })
    }

    /// Creates the schema. Returns whether FTS5 cue search is usable.
    fn migrate(conn: &mut Connection) -> rusqlite::Result<bool> {
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY,
                srt_path TEXT NOT NULL UNIQUE,
                media_path TEXT,
                title TEXT NOT NULL,
                channel TEXT,
                source_url TEXT,
                channel_url TEXT,
                duration_seconds REAL,
                views INTEGER,
                likes INTEGER,
                comments INTEGER,
                upload_timestamp TEXT,
                transcription_timestamp TEXT,
                has_human_subs INTEGER,
                has_automatic_subs INTEGER,
                model TEXT,
                language TEXT,
                segments_count INTEGER,
                version TEXT,
                commit_hash TEXT,
                cue_count INTEGER NOT NULL DEFAULT 0,
                srt_mtime INTEGER
            );
            CREATE TABLE IF NOT EXISTS cues (
                id INTEGER PRIMARY KEY,
                video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                cue_index INTEGER NOT NULL,
                start_seconds REAL NOT NULL,
                end_seconds REAL NOT NULL,
                text TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cues_video ON cues(video_id, start_seconds);
            CREATE INDEX IF NOT EXISTS idx_videos_upload ON videos(upload_timestamp);
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY,
                date TEXT,
                model TEXT,
                source TEXT,
                status TEXT,
                task_total INTEGER NOT NULL DEFAULT 0,
                task_done INTEGER NOT NULL DEFAULT 0,
                task_titles TEXT
            );",
        )?;

        // FTS5 is optional in SQLite builds; fall back to LIKE search when the
        // bundled library does not have it.
        let created = conn.execute_batch(
            "CREATE VIRTUAL TABLE IF NOT EXISTS cues_fts USING fts5(
                text,
                content='cues',
                content_rowid='id'
             );",
        );
        if created.is_err() {
            return Ok(false);
        }
        // A rebuild is idempotent and cheap, and repairs an FTS index that was
        // left out of step with the cue table.
        if conn
            .execute_batch("INSERT INTO cues_fts(cues_fts) VALUES('rebuild');")
            .is_ok()
        {
            Ok(true)
        } else {
            let _ = conn.execute_batch("DROP TABLE IF EXISTS cues_fts;");
            Ok(false)
        }
    }

    /// Walks the library and inserts or refreshes what changed. Returns the
    /// number of subtitle files seen.
    pub fn scan(&self, library: &Path) -> rusqlite::Result<usize> {
        let mut touched = 0usize;
        let mut seen: Vec<String> = Vec::new();
        if library.exists() {
            for entry in walkdir::WalkDir::new(library)
                .max_depth(3)
                .into_iter()
                .filter_map(Result::ok)
            {
                let path = entry.path();
                if path.extension().and_then(|e| e.to_str()) != Some("srt") {
                    continue;
                }
                // `<name>.unfinished.srt` is a work in progress, not a result.
                let Some(stem) = path.file_stem().and_then(|s| s.to_str()) else {
                    continue;
                };
                if stem.ends_with(".unfinished") {
                    continue;
                }
                seen.push(path_str(path));
                self.upsert(path, library)?;
                touched += 1;
            }
        }
        self.purge_missing(&seen);
        Ok(touched)
    }

    /// Drops rows whose subtitle file disappeared, so removed videos stop
    /// showing up in search results.
    fn purge_missing(&self, seen: &[String]) {
        let paths: Vec<String> = {
            let Ok(mut stmt) = self.conn.prepare("SELECT srt_path FROM videos") else {
                return;
            };
            let Ok(rows) = stmt.query_map([], |row| row.get::<_, String>(0)) else {
                return;
            };
            rows.filter_map(Result::ok).collect()
        };
        for path in paths.iter().filter(|p| !seen.iter().any(|s| s == *p)) {
            let _ = self.delete_video(path);
        }
    }

    /// Removes a video's cues from the FTS index.
    ///
    /// `cues_fts` is an external-content table, so plain `DELETE` is not
    /// available: FTS5 requires the 'delete' command together with the indexed
    /// values, and only if they are supplied before the content rows go away.
    fn purge_cues_fts(&self, video_id: i64) -> rusqlite::Result<()> {
        if !self.fts {
            return Ok(());
        }
        let cues: Vec<(i64, String)> = {
            let mut stmt = self
                .conn
                .prepare("SELECT id, text FROM cues WHERE video_id = ?1")?;
            let rows = stmt.query_map(params![video_id], |row| {
                Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?))
            })?;
            rows.filter_map(Result::ok).collect()
        };
        let mut stmt = self
            .conn
            .prepare("INSERT INTO cues_fts(cues_fts, rowid, text) VALUES('delete', ?1, ?2)")?;
        for (rowid, text) in cues {
            stmt.execute(params![rowid, text])?;
        }
        Ok(())
    }

    fn delete_video(&self, srt_path: &str) -> rusqlite::Result<()> {
        let video_id: Option<i64> = self
            .conn
            .query_row(
                "SELECT id FROM videos WHERE srt_path = ?1",
                params![srt_path],
                |row| row.get(0),
            )
            .optional()?;
        if let Some(video_id) = video_id {
            self.purge_cues_fts(video_id)?;
            self.conn
                .execute("DELETE FROM cues WHERE video_id = ?1", params![video_id])?;
        }
        self.conn
            .execute("DELETE FROM videos WHERE srt_path = ?1", params![srt_path])?;
        Ok(())
    }

    fn upsert(&self, srt_path: &Path, library: &Path) -> rusqlite::Result<()> {
        let mtime = file_mtime_seconds(srt_path);
        let existing: Option<i64> = self
            .conn
            .query_row(
                "SELECT srt_mtime FROM videos WHERE srt_path = ?1",
                params![path_str(srt_path)],
                |row| row.get(0),
            )
            .optional()?;

        if let (Some(old), Some(new)) = (existing, mtime) {
            if old == new {
                return Ok(());
            }
        }

        let metadata = read_metadata(srt_path);
        let cues = srt::parse_srt(srt_path);
        let media = find_media(
            srt_path,
            metadata.str("model").as_deref(),
            metadata.str("source_url").as_deref(),
        );
        let title = metadata
            .str("title")
            .unwrap_or_else(|| title_from_path(srt_path, library));

        self.conn.execute(
            "INSERT INTO videos (
                srt_path, media_path, title, channel, source_url, channel_url,
                duration_seconds, views, likes, comments, upload_timestamp,
                transcription_timestamp, has_human_subs, has_automatic_subs,
                model, language, segments_count, version, commit_hash,
                cue_count, srt_mtime
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12,
                       ?13, ?14, ?15, ?16, ?17, ?18, ?19, ?20, ?21)
             ON CONFLICT(srt_path) DO UPDATE SET
                media_path = excluded.media_path,
                title = excluded.title,
                channel = excluded.channel,
                source_url = excluded.source_url,
                channel_url = excluded.channel_url,
                duration_seconds = excluded.duration_seconds,
                views = excluded.views,
                likes = excluded.likes,
                comments = excluded.comments,
                upload_timestamp = excluded.upload_timestamp,
                transcription_timestamp = excluded.transcription_timestamp,
                has_human_subs = excluded.has_human_subs,
                has_automatic_subs = excluded.has_automatic_subs,
                model = excluded.model,
                language = excluded.language,
                segments_count = excluded.segments_count,
                version = excluded.version,
                commit_hash = excluded.commit_hash,
                cue_count = excluded.cue_count,
                srt_mtime = excluded.srt_mtime",
            params![
                path_str(srt_path),
                media.as_deref().map(path_str),
                title,
                metadata.str("channel_name"),
                metadata.str("source_url"),
                metadata.str("channel_url"),
                metadata.num("duration_seconds"),
                metadata.int("views"),
                metadata.int("likes"),
                metadata.int("comments_count"),
                metadata.str("upload_timestamp"),
                metadata
                    .str("transcription_timestamp")
                    .or_else(|| metadata.str("date")),
                metadata.boolean("has_human_subs"),
                metadata.boolean("has_automatic_subs"),
                metadata.str("model"),
                metadata.str("language"),
                metadata.int("segments_count"),
                metadata.str("version"),
                metadata.str("commit_hash"),
                cues.len() as i64,
                mtime,
            ],
        )?;

        let video_id = self.conn.query_row(
            "SELECT id FROM videos WHERE srt_path = ?1",
            params![path_str(srt_path)],
            |row| row.get::<_, i64>(0),
        )?;
        self.purge_cues_fts(video_id)?;
        self.conn
            .execute("DELETE FROM cues WHERE video_id = ?1", params![video_id])?;

        let mut stmt = self.conn.prepare(
            "INSERT INTO cues (video_id, cue_index, start_seconds, end_seconds, text)
             VALUES (?1, ?2, ?3, ?4, ?5)",
        )?;
        let mut fts_stmt = if self.fts {
            Some(
                self.conn
                    .prepare("INSERT INTO cues_fts (rowid, text) VALUES (?1, ?2)")?,
            )
        } else {
            None
        };
        for cue in &cues {
            stmt.execute(params![
                video_id,
                cue.index as i64,
                cue.start.as_secs_f64(),
                cue.end.as_secs_f64(),
                cue.text,
            ])?;
            if let Some(fts_stmt) = fts_stmt.as_mut() {
                let rowid = self.conn.last_insert_rowid();
                fts_stmt.execute(params![rowid, cue.text])?;
            }
        }
        Ok(())
    }

    /// Imports `jobs.json`, which the Python side rewrites in place.
    pub fn import_jobs(&self, jobs_file: &Path) -> usize {
        let Ok(text) = std::fs::read_to_string(jobs_file) else {
            return 0;
        };
        let Ok(jobs) = serde_json::from_str::<Vec<JobFile>>(&text) else {
            return 0;
        };
        if self.conn.execute("DELETE FROM jobs", []).is_err() {
            return 0;
        }
        let Ok(mut stmt) = self.conn.prepare(
            "INSERT INTO jobs (id, date, model, source, status, task_total, task_done, task_titles)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
        ) else {
            return 0;
        };
        let mut count = 0;
        for job in &jobs {
            let total = job.tasks.len() as i64;
            let done = job
                .tasks
                .iter()
                .filter(|t| matches!(t.status.as_deref().unwrap_or(""), "completed" | "skipped"))
                .count() as i64;
            let titles: Vec<String> = job
                .tasks
                .iter()
                .map(|t| t.title.clone().unwrap_or_else(|| t.source.clone()))
                .collect();
            if stmt
                .execute(params![
                    job.id,
                    job.date.clone(),
                    job.model.clone(),
                    job.source.clone(),
                    job.status.clone().unwrap_or_default(),
                    total,
                    done,
                    titles.join("\n"),
                ])
                .is_err()
            {
                continue;
            }
            count += 1;
        }
        count
    }

    /// Library search: title, channel, urls, model, language, and dates.
    /// Library search: title, channel, urls, model, language, dates, and counts.
    ///
    /// A query that reads as a number is also matched against views, likes,
    /// comments, and duration, so "1.5M" or "1500" finds a video by its statistics
    /// and "12:30" finds one by running time.
    pub fn search_videos(&self, query: &str, limit: usize) -> rusqlite::Result<Vec<Video>> {
        let pattern = like_pattern(query);
        let stats = stat_targets(query);
        let sql = format!(
            "SELECT {VIDEO_COLUMNS}
             FROM videos
             WHERE ?1 = '%%'
                OR lower(title) LIKE ?1 ESCAPE '\\'
                OR lower(coalesce(channel, '')) LIKE ?1 ESCAPE '\\'
                OR lower(coalesce(source_url, '')) LIKE ?1 ESCAPE '\\'
                OR lower(coalesce(channel_url, '')) LIKE ?1 ESCAPE '\\'
                OR lower(coalesce(model, '')) LIKE ?1 ESCAPE '\\'
                OR lower(coalesce(language, '')) LIKE ?1 ESCAPE '\\'
                OR lower(coalesce(upload_timestamp, '')) LIKE ?1 ESCAPE '\\'
                OR lower(coalesce(transcription_timestamp, '')) LIKE ?1 ESCAPE '\\'
                OR (?3 IS NOT NULL AND (
                       views = ?3
                    OR likes = ?3
                    OR comments = ?3
                    OR CAST(duration_seconds AS INTEGER) = ?3
                ))
             ORDER BY coalesce(upload_timestamp, transcription_timestamp, '') DESC, title
             LIMIT ?2"
        );
        let mut stmt = self.conn.prepare(&sql)?;
        let rows = stmt.query_map(params![pattern, limit as i64, stats], row_to_video)?;
        Ok(rows.filter_map(Result::ok).collect())
    }

    pub fn search_jobs(&self, query: &str, limit: usize) -> rusqlite::Result<Vec<Job>> {
        let pattern = like_pattern(query);
        let mut stmt = self.conn.prepare(
            "SELECT id, date, model, source, status, task_total, task_done, task_titles
             FROM jobs
             WHERE ?1 = '%%'
                OR lower(source) LIKE ?1 ESCAPE '\\'
                OR lower(coalesce(model, '')) LIKE ?1 ESCAPE '\\'
                OR lower(coalesce(status, '')) LIKE ?1 ESCAPE '\\'
                OR lower(coalesce(date, '')) LIKE ?1 ESCAPE '\\'
                OR lower(coalesce(task_titles, '')) LIKE ?1 ESCAPE '\\'
             ORDER BY id DESC
             LIMIT ?2",
        )?;
        let rows = stmt.query_map(params![pattern, limit as i64], row_from_job)?;
        Ok(rows.filter_map(Result::ok).collect())
    }

    /// Cue search. Uses FTS5 prefix matching when available, LIKE otherwise.
    pub fn search_cues(&self, query: &str, limit: usize) -> rusqlite::Result<Vec<CueHit>> {
        if self.fts && !query.trim().is_empty() {
            let sql = "SELECT c.video_id, c.cue_index, c.start_seconds, c.end_seconds, c.text
             FROM cues_fts f JOIN cues c ON c.id = f.rowid
             WHERE cues_fts MATCH ?1
             ORDER BY bm25(cues_fts), c.video_id, c.start_seconds
             LIMIT ?2";
            let hits = self
                .conn
                .prepare(sql)?
                .query_map(params![fts_query(query), limit as i64], cue_from_row)?
                .collect::<rusqlite::Result<Vec<_>>>();
            if let Ok(hits) = hits {
                return Ok(hits);
            }
        }

        let mut stmt = self.conn.prepare(
            "SELECT c.video_id, c.cue_index, c.start_seconds, c.end_seconds, c.text
             FROM cues c
             WHERE ?1 = '%%' OR c.text LIKE ?1 ESCAPE '\\'
             ORDER BY c.video_id, c.start_seconds
             LIMIT ?2",
        )?;
        let rows = stmt.query_map(params![like_pattern(query), limit as i64], cue_from_row)?;
        Ok(rows.filter_map(Result::ok).collect())
    }

    pub fn video_by_id(&self, id: i64) -> rusqlite::Result<Option<Video>> {
        let sql = format!("SELECT {VIDEO_COLUMNS} FROM videos WHERE id = ?1");
        self.conn
            .query_row(&sql, params![id], row_to_video)
            .optional()
    }

    pub fn cues_for_video(&self, video_id: i64) -> rusqlite::Result<Vec<Cue>> {
        let mut stmt = self.conn.prepare(
            "SELECT cue_index, start_seconds, end_seconds, text
             FROM cues WHERE video_id = ?1 ORDER BY start_seconds",
        )?;
        let rows = stmt.query_map(params![video_id], |row| {
            Ok(Cue {
                index: row.get::<_, i64>(0)? as usize,
                start: Duration::from_secs_f64(row.get(1)?),
                end: Duration::from_secs_f64(row.get(2)?),
                text: row.get(3)?,
            })
        })?;
        Ok(rows.filter_map(Result::ok).collect())
    }

    pub fn counts(&self) -> (usize, usize) {
        let videos = self
            .conn
            .query_row("SELECT count(*) FROM videos", [], |r| r.get::<_, i64>(0))
            .unwrap_or(0);
        let cues = self
            .conn
            .query_row("SELECT count(*) FROM cues", [], |r| r.get::<_, i64>(0))
            .unwrap_or(0);
        (videos as usize, cues as usize)
    }
}

fn cue_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<CueHit> {
    Ok(CueHit {
        video_id: row.get(0)?,
        cue_index: row.get(1)?,
        start_seconds: row.get(2)?,
        end_seconds: row.get(3)?,
        text: row.get(4)?,
    })
}

fn row_from_job(row: &rusqlite::Row<'_>) -> rusqlite::Result<Job> {
    let titles: Option<String> = row.get(7)?;
    Ok(Job {
        id: row.get(0)?,
        date: row.get(1)?,
        model: row.get(2)?,
        source: row.get(3)?,
        status: row.get(4)?,
        task_total: row.get(5)?,
        task_done: row.get(6)?,
        task_titles: titles
            .map(|t| t.lines().map(str::to_string).collect())
            .unwrap_or_default(),
    })
}

fn row_to_video(row: &rusqlite::Row<'_>) -> rusqlite::Result<Video> {
    Ok(Video {
        id: row.get(0)?,
        srt_path: PathBuf::from(row.get::<_, String>(1)?),
        media_path: row.get::<_, Option<String>>(2)?.map(PathBuf::from),
        title: row.get(3)?,
        channel: row.get(4)?,
        source_url: row.get(5)?,
        channel_url: row.get(6)?,
        duration_seconds: row.get(7)?,
        views: row.get(8)?,
        likes: row.get(9)?,
        comments: row.get(10)?,
        upload_timestamp: row.get(11)?,
        transcription_timestamp: row.get(12)?,
        has_human_subs: row.get(13)?,
        has_automatic_subs: row.get(14)?,
        model: row.get(15)?,
        language: row.get(16)?,
        segments_count: row.get(17)?,
        version: row.get(18)?,
        commit_hash: row.get(19)?,
        cue_count: row.get(20)?,
        srt_mtime: row.get(21)?,
    })
}

/// `%query%` with the LIKE wildcards inside the query escaped, so searching
/// for `100%` does not match everything.
/// Interprets a query as a statistic, returning the number to match against
/// views, likes, comments, or duration.
///
/// Accepts a plain count ("1500"), a thousands-separated count ("1,500"), a
/// compact suffix ("1.5K", "2M", "3B"), or a timestamp ("12:30", "1:02:03").
/// Anything else yields `None`, so text searches are unaffected.
fn stat_targets(query: &str) -> Option<i64> {
    let trimmed = query.trim();
    if trimmed.is_empty() {
        return None;
    }

    if let Some(seconds) = parse_timestamp(trimmed) {
        return Some(seconds);
    }

    let (digits, multiplier) = match trimmed.chars().last()? {
        'k' | 'K' => (&trimmed[..trimmed.len() - 1], 1_000f64),
        'm' | 'M' => (&trimmed[..trimmed.len() - 1], 1_000_000f64),
        'b' | 'B' => (&trimmed[..trimmed.len() - 1], 1_000_000_000f64),
        _ => (trimmed, 1f64),
    };
    let cleaned: String = digits.chars().filter(|c| *c != ',' && *c != '_').collect();
    let value: f64 = cleaned.parse().ok()?;
    // Reject nonsense rather than silently matching nothing useful.
    if !value.is_finite() || value < 0.0 {
        return None;
    }
    Some((value * multiplier).round() as i64)
}

/// Parses `ss`, `mm:ss`, or `hh:mm:ss` into seconds.
fn parse_timestamp(query: &str) -> Option<i64> {
    if !query.contains(':') {
        return None;
    }
    let mut total = 0i64;
    for part in query.split(':') {
        let field: i64 = part.parse().ok()?;
        if !(0..=59).contains(&field) {
            return None;
        }
        total = total * 60 + field;
    }
    Some(total)
}

fn like_pattern(query: &str) -> String {
    if query.trim().is_empty() {
        return "%%".into();
    }
    let mut escaped = String::with_capacity(query.len() + 2);
    for c in query.to_lowercase().chars() {
        if matches!(c, '\\' | '%' | '_') {
            escaped.push('\\');
        }
        escaped.push(c);
    }
    format!("%{escaped}%")
}

/// Turns user text into an FTS5 prefix query: `hello wor` -> `"hello"* AND "wor"*`.
fn fts_query(query: &str) -> String {
    query
        .split_whitespace()
        .map(|token| format!("\"{}\"*", token.replace('"', "\"\"")))
        .collect::<Vec<_>>()
        .join(" AND ")
}

/// `jobs.json`, as written by whisper_subs.py.
#[derive(Debug, Deserialize)]
struct JobFile {
    id: i64,
    #[serde(default)]
    date: Option<String>,
    #[serde(default)]
    model: Option<String>,
    #[serde(default)]
    source: String,
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    tasks: Vec<TaskFile>,
}

#[derive(Debug, Deserialize)]
struct TaskFile {
    #[serde(default)]
    source: String,
    #[serde(default)]
    title: Option<String>,
    #[serde(default)]
    status: Option<String>,
}

/// Metadata fields are read leniently: the Python side adds keys over time and
/// a malformed value must not drop the whole video from the index.
struct Metadata(serde_json::Value);

impl Metadata {
    fn str(&self, key: &str) -> Option<String> {
        self.0.get(key)?.as_str().map(str::to_string)
    }

    fn num(&self, key: &str) -> Option<f64> {
        self.0.get(key)?.as_f64()
    }

    fn int(&self, key: &str) -> Option<i64> {
        match self.0.get(key)? {
            serde_json::Value::Number(n) => n.as_i64().or_else(|| n.as_f64().map(|f| f as i64)),
            serde_json::Value::String(s) => s.trim().parse().ok(),
            _ => None,
        }
    }

    fn boolean(&self, key: &str) -> Option<bool> {
        self.0.get(key)?.as_bool()
    }
}

fn read_metadata(srt_path: &Path) -> Metadata {
    let meta_path = srt_path.with_extension("metadata.json");
    std::fs::read_to_string(meta_path)
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .map(Metadata)
        .unwrap_or(Metadata(serde_json::Value::Null))
}

const MEDIA_EXTENSIONS: [&str; 8] = ["mp4", "m4a", "mp3", "webm", "mkv", "wav", "flac", "ogg"];

/// Finds the media a subtitle belongs to.
///
/// whisper_subs.py writes subtitles as `<title>.<model>.srt` and numbered
/// force-mode backups as `<title>.2.srt`, while downloaded audio lives in
/// `~/.cache/whisper-subs/audio` keyed by source URL. So try, in order: the
/// media file named in the metadata, the audio cache entry for the source URL,
/// then sibling files with the model and backup suffixes removed.
fn find_media(srt_path: &Path, model: Option<&str>, source_url: Option<&str>) -> Option<PathBuf> {
    let parent = srt_path.parent()?;
    let stem = srt_path.file_stem()?.to_str()?;

    if let Some(name) = read_metadata(srt_path).str("source_file") {
        let sibling = parent.join(&name);
        if sibling.exists() {
            return Some(sibling);
        }
    }
    if let Some(cached) = source_url.and_then(audio_cache_path) {
        if cached.exists() {
            return Some(cached);
        }
    }

    for candidate_stem in stem_candidates(stem, model) {
        for ext in MEDIA_EXTENSIONS {
            let candidate = parent.join(format!("{candidate_stem}.{ext}"));
            if candidate.exists() {
                return Some(candidate);
            }
        }
    }
    None
}

/// Stems to try for a subtitle file: `<name>.<model>.srt` should also find
/// `<name>.m4a`, and `<name>.2.srt` should find `<name>.m4a`.
fn stem_candidates<'a>(stem: &'a str, model: Option<&str>) -> Vec<&'a str> {
    let mut out: Vec<&str> = Vec::new();
    if let Some(bare) = strip_model_suffix(stem, model) {
        out.push(bare);
    }
    if let Some(bare) = strip_backup_suffix(stem) {
        if !out.contains(&bare) {
            out.push(bare);
        }
    }
    out
}

fn strip_model_suffix<'a>(stem: &'a str, model: Option<&str>) -> Option<&'a str> {
    let suffix = format!(".{}", model?.replace(':', "_"));
    stem.strip_suffix(&suffix)
}

fn strip_backup_suffix(stem: &str) -> Option<&str> {
    let (_, digits) = stem.rsplit_once('.')?;
    if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    Some(&stem[..stem.len() - digits.len() - 1])
}

/// Looks a source URL up in the Python audio cache, which records the media
/// path per source in `index.json`.
fn audio_cache_path(source_url: &str) -> Option<PathBuf> {
    let home = std::env::var_os("HOME")?;
    let index = PathBuf::from(home).join(".cache/whisper-subs/audio/index.json");
    let text = std::fs::read_to_string(index).ok()?;
    let value: serde_json::Value = serde_json::from_str(&text).ok()?;
    let entries = value.get("entries")?.as_object()?;
    let entry = entries
        .values()
        .find(|e| e.get("source").and_then(|s| s.as_str()) == Some(source_url))?;
    Some(PathBuf::from(entry.get("path")?.as_str()?))
}

/// Falls back to the filename, which carries the date and title whisper_subs
/// writes when no metadata.json is present.
fn title_from_path(srt_path: &Path, library: &Path) -> String {
    let name = srt_path
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_default();
    let channel = srt_path
        .parent()
        .and_then(|p| p.strip_prefix(library).ok())
        .map(|rel| rel.display().to_string())
        .unwrap_or_default();
    if channel.is_empty() {
        name
    } else {
        format!("{name} [{channel}]")
    }
}

fn path_str(p: &Path) -> String {
    p.to_string_lossy().to_string()
}

fn file_mtime_seconds(path: &Path) -> Option<i64> {
    let meta = std::fs::metadata(path).ok()?;
    let modified = meta.modified().ok()?;
    let secs = modified
        .duration_since(SystemTime::UNIX_EPOCH)
        .ok()?
        .as_secs();
    Some(secs as i64)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Config;

    const SAMPLE_SRT: &str = "\
1
00:00:00,000 --> 00:00:02,500
the first spoken line

2
00:00:02,500 --> 00:00:05,000
a completely different phrase

3
00:01:00,000 --> 00:01:02,000
a later remark about widgets
";

    /// A private directory per test, so cases cannot see each other's files and
    /// a failing run leaves evidence behind.
    fn temp_dir(name: &str) -> PathBuf {
        use std::sync::atomic::{AtomicU64, Ordering};
        static COUNTER: AtomicU64 = AtomicU64::new(0);
        let unique = COUNTER.fetch_add(1, Ordering::Relaxed);
        let dir = std::env::temp_dir().join(format!(
            "ws-index-test-{name}-{}-{unique}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn write(path: &Path, contents: &str) {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        std::fs::write(path, contents).unwrap();
    }

    /// An index rooted in a private cache directory, so tests never touch the
    /// user's real `~/.cache/whisper-subs/tui-index.sqlite`.
    fn open_index(dir: &Path) -> Index {
        let config = Config {
            cache_dir: dir.join("cache"),
            ..Config::default()
        };
        Index::open(&config).unwrap()
    }

    /// Writes `<channel>/<stem>.srt` plus metadata, returning the SRT path.
    fn fixture_video(library: &Path, channel: &str, stem: &str, metadata: &str) -> PathBuf {
        let srt = library.join(channel).join(format!("{stem}.srt"));
        write(&srt, SAMPLE_SRT);
        if !metadata.is_empty() {
            write(
                &library.join(channel).join(format!("{stem}.metadata.json")),
                metadata,
            );
        }
        srt
    }

    #[test]
    fn reads_metadata_written_by_the_python_side() {
        let dir = temp_dir("metadata");
        let library = dir.join("library");
        fixture_video(
            &library,
            "Some Channel",
            "A Talk About Things",
            r#"{
                "channel_name": "Some Channel",
                "channel_url": "https://www.youtube.com/@some",
                "source_url": "https://www.youtube.com/watch?v=abc",
                "duration_seconds": 3661.5,
                "views": 1234,
                "likes": 56,
                "comments_count": 78,
                "upload_timestamp": "20260101",
                "model": "large-v3",
                "language": "en",
                "segments_count": 3,
                "version": "2.0.0",
                "commit_hash": "deadbeef",
                "has_human_subs": false,
                "has_automatic_subs": true
            }"#,
        );

        let index = open_index(&dir);
        assert_eq!(index.scan(&library).unwrap(), 1);

        let found = index.search_videos("things", 10).unwrap();
        assert_eq!(found.len(), 1, "search should find the fixture");
        let v = &found[0];
        assert_eq!(v.channel.as_deref(), Some("Some Channel"));
        assert_eq!(
            v.channel_url.as_deref(),
            Some("https://www.youtube.com/@some")
        );
        assert_eq!(
            v.source_url.as_deref(),
            Some("https://www.youtube.com/watch?v=abc")
        );
        assert_eq!(v.duration_seconds, Some(3661.5));
        assert_eq!(v.views, Some(1234));
        assert_eq!(v.likes, Some(56));
        assert_eq!(v.comments, Some(78));
        assert_eq!(v.upload_timestamp.as_deref(), Some("20260101"));
        assert_eq!(v.model.as_deref(), Some("large-v3"));
        assert_eq!(v.language.as_deref(), Some("en"));
        assert_eq!(v.segments_count, Some(3));
        assert_eq!(v.version.as_deref(), Some("2.0.0"));
        assert_eq!(v.commit_hash.as_deref(), Some("deadbeef"));
        assert_eq!(v.has_human_subs, Some(false));
        assert_eq!(v.has_automatic_subs, Some(true));
        assert_eq!(v.cue_count, 3);

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_subtitle_without_metadata_still_indexes() {
        let dir = temp_dir("no-metadata");
        let library = dir.join("library");
        fixture_video(&library, "Channel", "Bare Talk", "");

        let index = open_index(&dir);
        assert_eq!(index.scan(&library).unwrap(), 1);

        let found = index.search_videos("bare", 10).unwrap();
        assert_eq!(found.len(), 1);
        // Title falls back to the file name, qualified by the channel directory
        // so identically named videos stay distinguishable.
        assert_eq!(found[0].title, "Bare Talk [Channel]");
        assert!(found[0].views.is_none());
        assert!(found[0].model.is_none());

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn searches_cue_text_and_returns_offsets() {
        let dir = temp_dir("cues");
        let library = dir.join("library");
        fixture_video(&library, "Channel", "Talk", "");

        let index = open_index(&dir);
        index.scan(&library).unwrap();

        let hits = index.search_cues("widgets", 10).unwrap();
        assert_eq!(hits.len(), 1, "the third cue mentions widgets");
        assert_eq!(hits[0].cue_index, 3);
        assert!((hits[0].start_seconds - 60.0).abs() < 0.001);
        assert!((hits[0].end_seconds - 62.0).abs() < 0.001);

        // Partial words match too, so searching finds mid-sentence hits.
        assert_eq!(index.search_cues("spoken", 10).unwrap().len(), 1);
        assert_eq!(index.search_cues("nothing here", 10).unwrap().len(), 0);

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_rewritten_subtitle_replaces_its_cues() {
        let dir = temp_dir("rewrite");
        let library = dir.join("library");
        let srt = fixture_video(&library, "Channel", "Talk", "");

        let index = open_index(&dir);
        index.scan(&library).unwrap();
        assert_eq!(index.search_cues("spoken", 10).unwrap().len(), 1);

        // A different mtime is what marks the row stale; filesystem timestamp
        // granularity is 1s, so move the file's clock forward explicitly.
        write(
            &srt,
            "1\n00:00:00,000 --> 00:00:01,000\nreplacement words only\n",
        );
        bump_mtime(&srt, 60);

        index.scan(&library).unwrap();
        assert_eq!(index.counts(), (1, 1), "counts should be videos, cues");
        assert_eq!(
            index.search_cues("spoken", 10).unwrap().len(),
            0,
            "stale cue text must not survive a rewrite"
        );
        assert_eq!(index.search_cues("replacement", 10).unwrap().len(), 1);

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Pushes a file's mtime forward, since ext4 stores whole seconds and a
    /// fast test would otherwise rewrite within the same tick.
    fn bump_mtime(path: &Path, secs: i64) {
        let current = file_mtime_seconds(path).unwrap_or(0);
        let target = SystemTime::UNIX_EPOCH + Duration::from_secs((current + secs) as u64);
        let file = std::fs::File::options().write(true).open(path).unwrap();
        file.set_modified(target).unwrap();
    }

    #[test]
    fn purges_subtitles_that_left_the_library() {
        let dir = temp_dir("purge");
        let library = dir.join("library");
        let srt = fixture_video(&library, "Channel", "Talk", "");

        let index = open_index(&dir);
        index.scan(&library).unwrap();
        assert_eq!(index.counts().0, 1);

        std::fs::remove_file(&srt).unwrap();
        index.scan(&library).unwrap();

        assert_eq!(index.counts().0, 0, "deleted subtitle should be purged");
        assert_eq!(index.counts().1, 0, "its cues should be purged too");
        assert_eq!(index.search_cues("spoken", 10).unwrap().len(), 0);

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn finds_media_next_to_a_model_suffixed_subtitle() {
        let dir = temp_dir("media-suffix");
        let library = dir.join("library");
        // whisper_subs.py writes `<title>.<model>.srt` for the media `<title>`.
        fixture_video(
            &library,
            "Channel",
            "The Talk.large-v3",
            r#"{"model": "large-v3"}"#,
        );
        write(
            &library.join("Channel").join("The Talk.mp4"),
            "not really a video",
        );

        let index = open_index(&dir);
        index.scan(&library).unwrap();

        let found = index.search_videos("the talk", 10).unwrap();
        assert_eq!(found.len(), 1);
        let media = found[0].media_path.as_ref().expect("media should be found");
        assert_eq!(media.file_name().unwrap(), "The Talk.mp4");

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn finds_media_named_by_metadata() {
        let dir = temp_dir("media-metadata");
        let library = dir.join("library");
        // The download name rarely matches the subtitle stem, so metadata wins.
        fixture_video(
            &library,
            "Channel",
            "Odd Name",
            r#"{"source_file": "abc123.download.mp4", "model": "large-v3"}"#,
        );
        write(
            &library.join("Channel").join("abc123.download.mp4"),
            "not really a video",
        );

        let index = open_index(&dir);
        index.scan(&library).unwrap();

        let found = index.search_videos("odd", 10).unwrap();
        let media = found[0]
            .media_path
            .as_ref()
            .expect("metadata names the media");
        assert_eq!(media.file_name().unwrap(), "abc123.download.mp4");

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_subtitle_without_media_is_still_listed() {
        let dir = temp_dir("no-media");
        let library = dir.join("library");
        fixture_video(&library, "Channel", "Talk", "");

        let index = open_index(&dir);
        index.scan(&library).unwrap();

        let found = index.search_videos("talk", 10).unwrap();
        assert_eq!(found.len(), 1);
        assert!(found[0].media_path.is_none());

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn imports_jobs_from_the_python_history_file() {
        let dir = temp_dir("jobs");
        let jobs = dir.join("jobs.json");
        write(
            &jobs,
            r#"[
                {
                    "id": 7,
                    "date": "2026-01-02",
                    "model": "large-v3",
                    "source": "https://www.youtube.com/watch?v=zzz",
                    "status": "completed",
                    "tasks": [
                        {"source": "https://a", "title": "First Video", "status": "completed"},
                        {"source": "https://b", "title": "Second Video", "status": "failed"}
                    ]
                }
            ]"#,
        );

        let index = open_index(&dir);
        assert_eq!(index.import_jobs(&jobs), 1);

        let found = index.search_jobs("second", 10).unwrap();
        assert_eq!(found.len(), 1, "job search covers task titles");
        let job = &found[0];
        assert_eq!(job.id, 7);
        assert_eq!(job.model.as_deref(), Some("large-v3"));
        assert_eq!(job.task_total, 2);
        assert_eq!(job.task_done, 1, "only completed tasks count as done");
        assert!(job.task_titles.contains(&"First Video".to_string()));

        // A missing history file imports nothing rather than failing.
        assert_eq!(index.import_jobs(&dir.join("absent.json")), 0);

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn survives_reopening_the_index() {
        let dir = temp_dir("reopen");
        let library = dir.join("library");
        fixture_video(&library, "Channel", "Talk", "");

        {
            let index = open_index(&dir);
            index.scan(&library).unwrap();
        }

        // Reopening must keep the rows and must not re-add them on a rescan.
        let index = open_index(&dir);
        assert_eq!(index.counts(), (1, 3));
        index.scan(&library).unwrap();
        assert_eq!(index.counts(), (1, 3), "a second scan must not duplicate");
        assert_eq!(index.search_cues("spoken", 10).unwrap().len(), 1);

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn finds_videos_by_their_statistics() {
        let dir = temp_dir("stats");
        let library = dir.join("library");
        fixture_video(
            &library,
            "Channel",
            "Popular",
            r#"{"views": 1500000, "likes": 4200, "comments_count": 17, "duration_seconds": 750}"#,
        );
        fixture_video(
            &library,
            "Channel",
            "Quiet",
            r#"{"views": 12, "likes": 1, "comments_count": 0, "duration_seconds": 61}"#,
        );

        let index = open_index(&dir);
        assert_eq!(index.scan(&library).unwrap(), 2);

        // A plain count matches a view total.
        let by_views = index.search_videos("1500000", 10).unwrap();
        assert_eq!(by_views.len(), 1);
        assert_eq!(by_views[0].title, "Popular [Channel]");

        // A compact suffix resolves to the same number.
        assert_eq!(index.search_videos("1.5M", 10).unwrap().len(), 1);
        assert_eq!(index.search_videos("1,500,000", 10).unwrap().len(), 1);

        // Likes and comments are searchable too.
        assert_eq!(index.search_videos("4200", 10).unwrap().len(), 1);
        assert_eq!(index.search_videos("17", 10).unwrap().len(), 1);

        // Duration accepts both a timestamp and a raw second count.
        assert_eq!(index.search_videos("12:30", 10).unwrap().len(), 1);
        assert_eq!(index.search_videos("750", 10).unwrap().len(), 1);
        assert_eq!(index.search_videos("1:01", 10).unwrap().len(), 1);

        // A number nobody has still matches text, not statistics.
        assert!(index.search_videos("999999999", 10).unwrap().is_empty());

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_text_query_is_not_treated_as_a_statistic() {
        assert_eq!(stat_targets(""), None);
        assert_eq!(stat_targets("channel name"), None);
        assert_eq!(stat_targets("-5"), None);
        assert_eq!(stat_targets("1.5K"), Some(1_500));
        assert_eq!(stat_targets("2M"), Some(2_000_000));
        assert_eq!(stat_targets("3b"), Some(3_000_000_000));
        assert_eq!(stat_targets("1,234"), Some(1_234));
        assert_eq!(stat_targets("90"), Some(90));
        assert_eq!(stat_targets("12:30"), Some(750));
        assert_eq!(stat_targets("1:02:03"), Some(3_723));
        assert_eq!(stat_targets("99:99"), None);
    }

    #[test]
    fn search_escapes_like_wildcards() {
        let dir = temp_dir("wildcards");
        let library = dir.join("library");
        fixture_video(&library, "Channel", "Talk", "");

        let index = open_index(&dir);
        index.scan(&library).unwrap();

        // A bare `%` would otherwise match every row.
        assert_eq!(index.search_videos("%", 10).unwrap().len(), 0);

        let _ = std::fs::remove_dir_all(&dir);
    }
}
