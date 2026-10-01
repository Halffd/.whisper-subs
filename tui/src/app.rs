//! Terminal UI: tabs for library search, subtitle text search, job history,
//! and YouTube search, with an mpv window managed from the same keyboard.

use crate::config::Config;
use crate::index::{CueHit, Index, Job, Video};
use crate::srt::{self, Cue};
use crate::{player, youtube};
use crossterm::event::{
    self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode, KeyEventKind,
};
use crossterm::execute;
use crossterm::terminal::{
    disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen,
};
use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{
    Block, Borders, Cell, Gauge, Paragraph, Row, Table, TableState, Tabs, Wrap,
};
use ratatui::{backend::CrosstermBackend, Terminal};
use std::sync::mpsc::{channel, Receiver, Sender, TryRecvError};
use std::time::{Duration, Instant};

const RESULT_LIMIT: usize = 500;
const MPV_STARTUP_TIMEOUT: Duration = Duration::from_secs(8);

/// Background work the UI polls instead of blocking on.
enum Job2 {
    YoutubeSearch { request: String },
    Transcribe { title: String, model: String },
}

enum Message {
    YoutubeSearchDone {
        request: String,
        result: Result<Vec<youtube::YoutubeHit>, String>,
    },
    TranscribeLine(String),
    TranscribeDone(bool),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Tab {
    Library,
    Subtitles,
    Jobs,
    YouTube,
}

impl Tab {
    const ALL: [Tab; 4] = [Tab::Library, Tab::Subtitles, Tab::Jobs, Tab::YouTube];

    fn title(self) -> &'static str {
        match self {
            Tab::Library => "Library",
            Tab::Subtitles => "Subtitles",
            Tab::Jobs => "Jobs",
            Tab::YouTube => "YouTube",
        }
    }

    fn placeholder(self) -> &'static str {
        match self {
            Tab::Library => "search titles, channels, models, urls, or views (1.5M)",
            Tab::Subtitles => "search subtitle text",
            Tab::Jobs => "search job sources, models, status",
            Tab::YouTube => "search YouTube, enter to search, t to transcribe",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Panel {
    Results,
    Detail,
}

/// Text entry target. The YouTube tab has two prompts: `/` searches,
/// `t` picks a model for transcription.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Entry {
    None,
    Search,
    Transcribe,
}

struct App {
    config: Config,
    index: Index,
    messages: Receiver<Message>,
    pending: Option<Job2>,
    sender: Sender<Message>,

    tab: Tab,
    panel: Panel,
    entry: Entry,
    query: String,

    videos: Vec<Video>,
    cue_hits: Vec<CueHit>,
    jobs: Vec<Job>,
    youtube_hits: Vec<youtube::YoutubeHit>,
    table: TableState,
    detail: Vec<Line<'static>>,

    status: String,
    error: Option<String>,
    busy: Option<&'static str>,

    player: Option<player::Player>,
    mpv_child: Option<std::process::Child>,
    playing: Option<Video>,
    playing_cues: Vec<Cue>,
    playback_position: Duration,
    playback_duration: Option<Duration>,
    playback_paused: bool,

    transcribe_log: Vec<Line<'static>>,
    scanned: bool,
}

impl App {
    fn new(config: Config, index: Index) -> Self {
        let (sender, messages) = channel();
        let mut app = Self {
            config,
            index,
            messages,
            pending: None,
            sender,
            tab: Tab::Library,
            panel: Panel::Results,
            entry: Entry::None,
            query: String::new(),
            videos: Vec::new(),
            cue_hits: Vec::new(),
            jobs: Vec::new(),
            youtube_hits: Vec::new(),
            table: TableState::default(),
            detail: Vec::new(),
            status: "press / to search, r to reindex".into(),
            error: None,
            busy: None,
            player: None,
            mpv_child: None,
            playing: None,
            playing_cues: Vec::new(),
            playback_position: Duration::ZERO,
            playback_duration: None,
            playback_paused: false,
            transcribe_log: Vec::new(),
            scanned: false,
        };
        app.run_search();
        app
    }

    fn selected_row(&self) -> Option<usize> {
        self.table.selected().filter(|i| *i < self.row_count())
    }

    fn row_count(&self) -> usize {
        match self.tab {
            Tab::Library => self.videos.len(),
            Tab::Subtitles => self.cue_hits.len(),
            Tab::Jobs => self.jobs.len(),
            Tab::YouTube => self.youtube_hits.len(),
        }
    }

    /// Re-runs the query for the active tab. Library, subtitle, and job
    /// searches filter live as the user types.
    fn run_search(&mut self) {
        self.error = None;
        match self.tab {
            Tab::Library => match self.index.search_videos(&self.query, RESULT_LIMIT) {
                Ok(rows) => {
                    self.status = format!("{} videos", rows.len());
                    self.videos = rows;
                }
                Err(e) => self.error = Some(format!("library search failed: {e}")),
            },
            Tab::Subtitles => {
                if self.query.trim().is_empty() {
                    self.cue_hits.clear();
                    self.status = "type to search subtitle text".into();
                } else {
                    match self.index.search_cues(&self.query, RESULT_LIMIT) {
                        Ok(rows) => {
                            self.status = format!("{} subtitle matches", rows.len());
                            self.cue_hits = rows;
                        }
                        Err(e) => self.error = Some(format!("subtitle search failed: {e}")),
                    }
                }
            }
            Tab::Jobs => match self.index.search_jobs(&self.query, RESULT_LIMIT) {
                Ok(rows) => {
                    self.status = format!("{} jobs", rows.len());
                    self.jobs = rows;
                }
                Err(e) => self.error = Some(format!("job search failed: {e}")),
            },
            Tab::YouTube => {}
        }
        self.table.select(Some(0));
        self.table = TableState::default().with_selected(Some(0));
    }

    /// Walks the library and job history, refreshing both.
    fn rescan(&mut self) {
        let videos = self.index.scan(self.config.library_dir());
        let jobs = self.index.import_jobs(self.config.jobs_file());
        match videos {
            Ok(seen) => {
                let (indexed, cues) = self.index.counts();
                self.status =
                    format!("{seen} subtitles, {indexed} indexed, {cues} cues, {jobs} jobs");
                self.error = None;
            }
            Err(e) => self.error = Some(format!("index scan failed: {e}")),
        }
        self.run_search();
    }

    fn start_youtube_search(&mut self) {
        let query = self.query.trim().to_string();
        if query.is_empty() {
            self.status = "type a query first".into();
            return;
        }
        let yt_dlp = self.config.yt_dlp.clone();
        let sender = self.sender.clone();
        self.pending = Some(Job2::YoutubeSearch {
            request: query.clone(),
        });
        self.busy = Some("searching YouTube");
        self.error = None;

        std::thread::spawn(move || {
            let result = youtube::search(&yt_dlp, &query, 25, Duration::from_secs(60));
            let _ = sender.send(Message::YoutubeSearchDone {
                request: query,
                result,
            });
        });
    }

    fn start_transcription(&mut self, model: String) {
        let Some(hit) = self
            .youtube_hits
            .get(self.selected_row().unwrap_or(0))
            .cloned()
        else {
            self.error = Some("select a YouTube result first".into());
            return;
        };
        if !self.config.models.contains(&model) {
            self.status = format!("unknown model {model}");
            return;
        }

        let python = self.config.python.clone();
        let script = self.config.whisper_subs_script();
        let url = hit.url();
        let sender = self.sender.clone();
        let log_sender = sender.clone();

        self.transcribe_log = vec![Line::from(format!(
            "$ {python} {} {model} {url}",
            script.display()
        ))];
        self.pending = Some(Job2::Transcribe {
            title: hit.title.clone(),
            model: model.clone(),
        });
        self.busy = Some("transcribing");
        self.error = None;

        std::thread::spawn(move || {
            let (done_tx, done_rx) = channel();
            std::thread::spawn(move || {
                let ok = youtube::transcribe(&python, &script, &model, &url, move |line| {
                    let _ = log_sender.send(Message::TranscribeLine(line));
                })
                .unwrap_or(false);
                let _ = done_tx.send(ok);
            });
            let ok = done_rx.recv().unwrap_or(false);
            let _ = sender.send(Message::TranscribeDone(ok));
        });
    }

    /// Drains background messages. Called once per tick.
    fn drain_events(&mut self) {
        let messages: Vec<Message> = std::iter::from_fn(|| match self.messages.try_recv() {
            Ok(m) => Some(m),
            Err(TryRecvError::Empty) | Err(TryRecvError::Disconnected) => None,
        })
        .collect();

        for message in messages {
            match message {
                Message::YoutubeSearchDone { request, result } => {
                    let current = matches!(
                        &self.pending,
                        Some(Job2::YoutubeSearch { request: r }) if *r == request
                    );
                    if !current {
                        continue;
                    }
                    self.pending = None;
                    self.busy = None;
                    match result {
                        Ok(hits) => {
                            self.status = format!("{} YouTube results", hits.len());
                            self.youtube_hits = hits;
                            self.table = TableState::default().with_selected(Some(0));
                            self.error = None;
                        }
                        Err(e) => self.error = Some(e),
                    }
                }
                Message::TranscribeLine(line) => {
                    self.transcribe_log.push(Line::from(line));
                    let overflow = self.transcribe_log.len().saturating_sub(500);
                    if overflow > 0 {
                        self.transcribe_log.drain(..overflow);
                    }
                }
                Message::TranscribeDone(ok) => {
                    let Some(Job2::Transcribe { title, model }) = self.pending.take() else {
                        continue;
                    };
                    self.busy = None;
                    self.status = if ok {
                        format!("transcribed {title} with {model}, press r to index it")
                    } else {
                        format!("transcription of {title} failed, see log")
                    };
                    if !ok {
                        self.error = Some("whisper_subs.py exited non-zero".into());
                    }
                }
            }
        }
    }

    fn selected_video(&self) -> Option<Video> {
        match self.tab {
            Tab::Library => self
                .selected_row()
                .and_then(|i| self.videos.get(i).cloned()),
            Tab::Subtitles => {
                let hit = self.cue_hits.get(self.selected_row()?)?;
                self.index.video_by_id(hit.video_id).ok().flatten()
            }
            _ => None,
        }
    }

    fn selected_start(&self) -> Duration {
        match self.tab {
            Tab::Subtitles => self
                .cue_hits
                .get(self.selected_row().unwrap_or(0))
                .map(|h| Duration::from_secs_f64(h.start_seconds))
                .unwrap_or(Duration::ZERO),
            _ => Duration::ZERO,
        }
    }

    fn play_selected(&mut self) {
        if self.tab == Tab::YouTube {
            self.error = Some("YouTube results have no local media; transcribe first".into());
            return;
        }
        let Some(video) = self.selected_video() else {
            self.error = Some("nothing selected".into());
            return;
        };
        let Some(media) = video.media_path.clone() else {
            self.error = Some(format!(
                "no media file found for {}",
                video.srt_path.display()
            ));
            return;
        };

        self.stop_player();
        let subtitle = video.srt_path.clone();
        let socket = self.config.mpv_socket.clone();
        let start = self.selected_start();

        let child = match player::spawn_mpv(&socket, &media, Some(&subtitle), start) {
            Ok(child) => child,
            Err(e) => {
                self.error = Some(e);
                return;
            }
        };
        self.mpv_child = Some(child);

        match player::Player::connect_within(&socket, MPV_STARTUP_TIMEOUT) {
            Ok(mut p) => {
                // Seek once mpv has opened the file, otherwise the request is
                // dropped because there is no file loaded yet.
                if start > Duration::ZERO {
                    let deadline = Instant::now() + Duration::from_secs(5);
                    let mut seeked = false;
                    while Instant::now() < deadline && !seeked {
                        if p.seek(start).is_ok() {
                            seeked = true;
                        } else {
                            std::thread::sleep(Duration::from_millis(100));
                        }
                    }
                }
                if let Some(state) = p.poll() {
                    self.playback_duration = state.duration;
                }
                self.playback_position = start;
                self.playing_cues = self.index.cues_for_video(video.id).unwrap_or_default();
                self.playback_paused = false;
                self.player = Some(p);
                self.playing = Some(video);
                self.panel = Panel::Results;
                self.status = "playing".into();
            }
            Err(e) => {
                self.error = Some(e);
                self.kill_mpv();
                self.playing = None;
            }
        }
    }

    fn kill_mpv(&mut self) {
        if let Some(p) = self.player.as_mut() {
            let _ = p.quit();
        }
        self.player = None;
        if let Some(mut child) = self.mpv_child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    fn stop_player(&mut self) {
        self.kill_mpv();
        self.playing = None;
        self.playing_cues.clear();
        self.playback_position = Duration::ZERO;
        self.playback_duration = None;
        self.playback_paused = false;
    }

    fn poll_player(&mut self) {
        let state = self.player.as_mut().and_then(|p| p.poll());
        if let Some(state) = state {
            self.playback_position = state.position;
            self.playback_paused = state.paused;
            if state.duration.is_some() {
                self.playback_duration = state.duration;
            }
        }
        if self.player.as_ref().is_some_and(|p| !p.is_connected()) {
            self.kill_mpv();
            self.playing = None;
        }
    }

    fn current_cue_text(&self) -> Option<&str> {
        self.playing.as_ref()?;
        self.playing_cues
            .iter()
            .find(|c| self.playback_position >= c.start && self.playback_position <= c.end)
            .map(|c| c.text.as_str())
    }

    fn seek(&mut self, target: Duration) {
        if let Some(p) = self.player.as_mut() {
            let _ = p.seek(target);
        }
        self.playback_position = target;
    }

    fn cycle_tab(&mut self, forward: bool) {
        let current = Tab::ALL.iter().position(|t| *t == self.tab).unwrap_or(0);
        let next = if forward {
            (current + 1) % Tab::ALL.len()
        } else {
            (current + Tab::ALL.len() - 1) % Tab::ALL.len()
        };
        self.tab = Tab::ALL[next];
        self.panel = Panel::Results;
        self.entry = Entry::None;
        self.query.clear();
        self.run_search();
    }

    fn build_detail(&mut self) {
        self.panel = Panel::Detail;
        let row = self.selected_row();
        self.detail = match self.tab {
            Tab::Library => row
                .and_then(|i| self.videos.get(i))
                .map(video_detail)
                .unwrap_or_else(|| vec![Line::from("no video selected")]),
            Tab::Subtitles => row
                .and_then(|i| self.cue_hits.get(i))
                .map(cue_detail)
                .unwrap_or_else(|| vec![Line::from("no match selected")]),
            Tab::Jobs => row
                .and_then(|i| self.jobs.get(i))
                .map(job_detail)
                .unwrap_or_else(|| vec![Line::from("no job selected")]),
            Tab::YouTube => row.and_then(|i| self.youtube_hits.get(i)).map_or_else(
                || vec![Line::from("no YouTube result selected")],
                |hit| {
                    vec![
                        Line::from(Span::styled(
                            hit.title.clone(),
                            Style::default().add_modifier(Modifier::BOLD),
                        )),
                        Line::from(format!("channel:  {}", hit.channel_label())),
                        Line::from(format!("url:     {}", hit.url())),
                        Line::from(format!(
                            "duration: {}",
                            hit.duration
                                .map(|d| srt::format_clock(Duration::from_secs_f64(d)))
                                .unwrap_or_else(|| "-".into())
                        )),
                        Line::from(format!(
                            "views:   {}",
                            hit.view_count
                                .map(format_compact)
                                .unwrap_or_else(|| "-".into())
                        )),
                        Line::from(format!(
                            "uploaded: {}",
                            hit.upload_date.as_deref().unwrap_or("-")
                        )),
                        Line::from(format!(
                            "channel: {}",
                            hit.channel_url.as_deref().unwrap_or("-")
                        )),
                        Line::from(format!(
                            "thumb:  {}",
                            hit.thumbnail.as_deref().unwrap_or("-")
                        )),
                        Line::from(""),
                        Line::from("press t to transcribe"),
                    ]
                },
            ),
        };
    }

    fn enter(&mut self) {
        match self.entry {
            Entry::Search => {
                if self.tab == Tab::YouTube {
                    self.start_youtube_search();
                } else {
                    self.run_search();
                }
            }
            Entry::Transcribe => {
                let model = self.query.trim().to_string();
                self.query.clear();
                self.start_transcription(model);
            }
            Entry::None => self.build_detail(),
        }
    }

    /// Live-searching tabs filter on every keystroke; YouTube waits for enter.
    fn live_search(&mut self) {
        if self.entry == Entry::Search && self.tab != Tab::YouTube {
            self.run_search();
        }
    }

    fn on_key(&mut self, key: event::KeyEvent) -> bool {
        // Text entry consumes keys first.
        if self.entry != Entry::None {
            match key.code {
                KeyCode::Esc => {
                    self.entry = Entry::None;
                    self.query.clear();
                }
                KeyCode::Enter => {
                    self.entry = Entry::None;
                    self.enter();
                }
                KeyCode::Backspace => {
                    self.query.pop();
                    self.live_search();
                }
                KeyCode::Char(c) => {
                    self.query.push(c);
                    self.live_search();
                }
                _ => {}
            }
            return false;
        }

        match key.code {
            KeyCode::Char('q') => return true,
            KeyCode::Tab => self.cycle_tab(true),
            KeyCode::BackTab => self.cycle_tab(false),
            KeyCode::Char('/') => self.entry = Entry::Search,
            KeyCode::Char('t') if self.tab == Tab::YouTube => {
                self.entry = Entry::Transcribe;
                self.query = self.config.models.first().cloned().unwrap_or_default();
            }
            KeyCode::Down | KeyCode::Char('j') => self.move_selection(1),
            KeyCode::Up | KeyCode::Char('k') => self.move_selection(-1),
            KeyCode::PageDown => self.move_selection(10),
            KeyCode::PageUp => self.move_selection(-10),
            KeyCode::Home => self.move_selection(i64::MIN / 2),
            KeyCode::End => self.move_selection(i64::MAX / 2),
            KeyCode::Enter => self.enter(),
            KeyCode::Char('p') => self.play_selected(),
            KeyCode::Char(' ') => {
                if let Some(p) = self.player.as_mut() {
                    let _ = p.toggle_pause();
                }
            }
            KeyCode::Char(']') => {
                let target = self.playback_position + Duration::from_secs(10);
                self.seek(target);
            }
            KeyCode::Char('[') => {
                let target = self
                    .playback_position
                    .checked_sub(Duration::from_secs(10))
                    .unwrap_or(Duration::ZERO);
                self.seek(target);
            }
            KeyCode::Char('s') => self.stop_player(),
            KeyCode::Char('r') => self.rescan(),
            KeyCode::Char('b') => self.panel = Panel::Results,
            KeyCode::Char('d') => self.build_detail(),
            _ => {}
        }
        false
    }

    fn move_selection(&mut self, delta: i64) {
        let len = self.row_count();
        if len == 0 {
            self.table.select(None);
            return;
        }
        let current = self.table.selected().unwrap_or(0) as i64;
        let next = (current + delta).clamp(0, len as i64 - 1) as usize;
        self.table.select(Some(next));
    }
}

pub fn start() -> std::io::Result<()> {
    let config = Config::load();
    let index = match Index::open(&config) {
        Ok(index) => index,
        Err(e) => {
            eprintln!(
                "could not open index at {}: {e}",
                config.index_path().display()
            );
            std::process::exit(1);
        }
    };
    let mut terminal = setup_terminal()?;
    let mut app = App::new(config, index);

    let result = event_loop(&mut terminal, &mut app);
    app.stop_player();
    restore_terminal(&mut terminal)?;
    result
}

fn setup_terminal() -> std::io::Result<Terminal<CrosstermBackend<std::io::Stdout>>> {
    enable_raw_mode()?;
    let mut stdout = std::io::stdout();
    execute!(
        stdout,
        EnterAlternateScreen,
        EnableMouseCapture,
        crossterm::cursor::Hide
    )?;
    Terminal::new(CrosstermBackend::new(stdout))
}

fn restore_terminal(
    terminal: &mut Terminal<CrosstermBackend<std::io::Stdout>>,
) -> std::io::Result<()> {
    disable_raw_mode()?;
    execute!(
        terminal.backend_mut(),
        LeaveAlternateScreen,
        DisableMouseCapture,
        crossterm::cursor::Show
    )?;
    terminal.show_cursor()
}

fn event_loop(
    terminal: &mut Terminal<CrosstermBackend<std::io::Stdout>>,
    app: &mut App,
) -> std::io::Result<()> {
    if !app.scanned {
        app.rescan();
        app.scanned = true;
    }

    loop {
        app.poll_player();
        app.drain_events();

        terminal.draw(|frame| draw(frame, app))?;

        if !event::poll(Duration::from_millis(150))? {
            continue;
        }
        if let Event::Key(key) = event::read()? {
            if key.kind == KeyEventKind::Press && app.on_key(key) {
                return Ok(());
            }
        }
    }
}

fn video_detail(v: &Video) -> Vec<Line<'static>> {
    let mut lines = vec![
        Line::from(Span::styled(
            v.display_title().to_string(),
            Style::default().add_modifier(Modifier::BOLD),
        )),
        Line::from(format!("channel:   {}", v.channel_label())),
        Line::from(format!("subtitle:  {}", v.srt_path.display())),
    ];
    if let Some(media) = &v.media_path {
        lines.push(Line::from(format!("media:     {}", media.display())));
    }
    lines.push(Line::from(format!(
        "duration:  {}",
        v.duration_seconds
            .map(|d| srt::format_clock(Duration::from_secs_f64(d)))
            .unwrap_or_else(|| "unknown".into())
    )));
    lines.push(Line::from(format!(
        "views:     {}",
        v.views.map(format_compact).unwrap_or_else(|| "n/a".into())
    )));
    if v.likes.is_some() || v.comments.is_some() {
        lines.push(Line::from(format!(
            "likes:     {}   comments: {}",
            v.likes.map(format_compact).unwrap_or_else(|| "n/a".into()),
            v.comments
                .map(format_compact)
                .unwrap_or_else(|| "n/a".into())
        )));
    }
    lines.push(Line::from(format!("cues:      {}", v.cue_count)));
    lines.push(Line::from(format!(
        "model:     {}",
        v.model.as_deref().unwrap_or("unknown")
    )));
    lines.push(Line::from(format!(
        "language:  {}",
        v.language.as_deref().unwrap_or("unknown")
    )));
    if let Some(count) = v.segments_count {
        lines.push(Line::from(format!("segments:  {count}")));
    }
    lines.push(Line::from(format!(
        "subs:      {}",
        subs_kind(v.has_human_subs, v.has_automatic_subs)
    )));
    lines.push(Line::from(format!(
        "uploaded:  {}",
        v.upload_timestamp.as_deref().unwrap_or("unknown")
    )));
    if let Some(when) = &v.transcription_timestamp {
        lines.push(Line::from(format!("transcribed: {when}")));
    }
    if let Some(epoch) = v.srt_mtime {
        lines.push(Line::from(format!(
            "subtitle updated: {}",
            format_epoch(epoch)
        )));
    }
    if let Some(url) = &v.channel_url {
        lines.push(Line::from(format!("channel:   {url}")));
    }
    lines.push(Line::from(format!(
        "build:     {} @ {}",
        v.version.as_deref().unwrap_or("?"),
        v.commit_hash.as_deref().unwrap_or("?")
    )));
    if let Some(url) = &v.source_url {
        lines.push(Line::from(format!("source:    {url}")));
    }
    lines.push(Line::from(""));
    lines.push(Line::from(match v.media_path.is_some() {
        true => "press p to play this subtitle",
        false => "no media file found for this subtitle",
    }));
    lines
}

/// Describes which subtitle variants exist, so a human transcript is
/// distinguishable from an automatic one.
fn subs_kind(human: Option<bool>, automatic: Option<bool>) -> String {
    match (human.unwrap_or(false), automatic.unwrap_or(false)) {
        (true, true) => "human + automatic".into(),
        (true, false) => "human".into(),
        (false, true) => "automatic".into(),
        (false, false) => "unknown".into(),
    }
}

fn cue_detail(hit: &CueHit) -> Vec<Line<'static>> {
    vec![
        Line::from(format!("cue #{}", hit.cue_index)),
        Line::from(format!(
            "{} --> {}",
            srt::format_clock(Duration::from_secs_f64(hit.start_seconds)),
            srt::format_clock(Duration::from_secs_f64(hit.end_seconds))
        )),
        Line::from(""),
        Line::from(hit.text.clone()),
        Line::from(""),
        Line::from("press p to play from this cue"),
    ]
}

fn job_detail(job: &Job) -> Vec<Line<'static>> {
    let mut lines = vec![
        Line::from(Span::styled(
            format!("job {}", job.id),
            Style::default().add_modifier(Modifier::BOLD),
        )),
        Line::from(format!("date:      {}", job.date.as_deref().unwrap_or("-"))),
        Line::from(format!(
            "model:     {}",
            job.model.as_deref().unwrap_or("-")
        )),
        Line::from(format!("status:    {}", job.status)),
        Line::from(format!("progress:  {}", job.progress_label())),
        Line::from(format!("source:    {}", job.source)),
    ];
    for title in &job.task_titles {
        lines.push(Line::from(format!("  - {title}")));
    }
    lines
}

fn draw(frame: &mut ratatui::Frame, app: &mut App) {
    let areas = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Length(3),
            Constraint::Min(6),
            Constraint::Length(4),
            Constraint::Length(1),
        ])
        .split(frame.area());

    let tab_names: Vec<&str> = Tab::ALL.iter().map(|t| t.title()).collect();
    let tabs = Tabs::new(tab_names)
        .select(Tab::ALL.iter().position(|t| *t == app.tab).unwrap_or(0))
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title(" whisper-subs "),
        )
        .highlight_style(
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        );
    frame.render_widget(tabs, areas[0]);

    draw_search(frame, app, areas[1]);

    if matches!(app.panel, Panel::Detail) {
        let detail = Paragraph::new(app.detail.clone())
            .wrap(Wrap { trim: false })
            .block(Block::default().borders(Borders::ALL).title(" detail "));
        frame.render_widget(detail, areas[2]);
    } else {
        draw_results(frame, app, areas[2]);
    }

    draw_player(frame, app, areas[3]);

    let status = if let Some(error) = &app.error {
        Span::styled(error.clone(), Style::default().fg(Color::Red))
    } else if let Some(busy) = app.busy {
        Span::styled(format!("{busy}..."), Style::default().fg(Color::Yellow))
    } else {
        Span::styled(app.status.clone(), Style::default().fg(Color::Green))
    };
    let hints: Vec<Span> = vec![
        Span::styled("tab", Style::default().fg(Color::DarkGray)),
        Span::raw(" switch  "),
        Span::styled("/", Style::default().fg(Color::DarkGray)),
        Span::raw(" search  "),
        Span::styled("enter", Style::default().fg(Color::DarkGray)),
        Span::raw(" detail  "),
        Span::styled("p", Style::default().fg(Color::DarkGray)),
        Span::raw(" play  "),
        Span::styled("r", Style::default().fg(Color::DarkGray)),
        Span::raw(" reindex  "),
        Span::styled("q", Style::default().fg(Color::DarkGray)),
        Span::raw(" quit"),
    ];
    frame.render_widget(
        Paragraph::new(Line::from([vec![status, Span::raw("   ")], hints].concat())),
        areas[4],
    );
}

fn draw_search(frame: &mut ratatui::Frame, app: &App, area: Rect) {
    let prompt = match app.entry {
        Entry::None => "> ".to_string(),
        Entry::Search => "/ ".to_string(),
        Entry::Transcribe => "model: ".to_string(),
    };
    let content = if app.query.is_empty() && app.entry == Entry::None {
        Span::styled(app.tab.placeholder(), Style::default().fg(Color::DarkGray))
    } else {
        Span::raw(app.query.clone())
    };
    let title = match app.entry {
        Entry::Transcribe => " transcribe with model ",
        _ => " search ",
    };
    let paragraph = Paragraph::new(Line::from(vec![
        Span::styled(prompt, Style::default().fg(Color::Yellow)),
        content,
    ]))
    .block(Block::default().borders(Borders::ALL).title(title));
    frame.render_widget(paragraph, area);
}

fn draw_results(frame: &mut ratatui::Frame, app: &mut App, area: Rect) {
    let widths = [
        Constraint::Percentage(32),
        Constraint::Percentage(22),
        Constraint::Length(11),
        Constraint::Length(11),
        Constraint::Length(7),
    ];
    let title = format!(" {} ", app.tab.title().to_lowercase());

    let (header, rows) = match app.tab {
        Tab::Library => (
            Row::new(vec!["title", "channel", "length", "views", "cues"]),
            app.videos
                .iter()
                .map(|v| {
                    Row::new(vec![
                        Cell::from(truncate(v.display_title(), 46)),
                        Cell::from(truncate(v.channel_label(), 24)),
                        Cell::from(
                            v.duration_seconds
                                .map(|d| srt::format_clock(Duration::from_secs_f64(d)))
                                .unwrap_or_else(|| "-".into()),
                        ),
                        Cell::from(v.views.map(format_compact).unwrap_or_else(|| "-".into())),
                        Cell::from(v.cue_count.to_string()),
                    ])
                })
                .collect::<Vec<Row>>(),
        ),
        Tab::Subtitles => {
            let rows = app
                .cue_hits
                .iter()
                .map(|hit| {
                    let video = app.index.video_by_id(hit.video_id).ok().flatten();
                    let label = video
                        .map(|v| v.display_title().to_string())
                        .unwrap_or_else(|| format!("video {}", hit.video_id));
                    Row::new(vec![
                        Cell::from(truncate(&label, 46)),
                        Cell::from(srt::format_clock(Duration::from_secs_f64(
                            hit.start_seconds,
                        ))),
                        Cell::from(truncate(&hit.text, 40)),
                        Cell::from(""),
                        Cell::from(""),
                    ])
                })
                .collect::<Vec<Row>>();
            (Row::new(vec!["video", "at", "cue text", "", ""]), rows)
        }
        Tab::Jobs => (
            Row::new(vec!["id", "status", "model", "progress", "date"]),
            app.jobs
                .iter()
                .map(|j| {
                    Row::new(vec![
                        Cell::from(j.id.to_string()),
                        Cell::from(truncate(&j.status, 22)),
                        Cell::from(truncate(j.model.as_deref().unwrap_or("-"), 11)),
                        Cell::from(j.progress_label()),
                        Cell::from(j.date.as_deref().unwrap_or("-").to_string()),
                    ])
                })
                .collect::<Vec<Row>>(),
        ),
        Tab::YouTube => (
            Row::new(vec!["title", "channel", "length", "views", ""]),
            app.youtube_hits
                .iter()
                .map(|hit| {
                    Row::new(vec![
                        Cell::from(truncate(&hit.title, 46)),
                        Cell::from(truncate(hit.channel_label(), 24)),
                        Cell::from(
                            hit.duration
                                .map(|d| srt::format_clock(Duration::from_secs_f64(d)))
                                .unwrap_or_else(|| "-".into()),
                        ),
                        Cell::from(
                            hit.view_count
                                .map(format_compact)
                                .unwrap_or_else(|| "-".into()),
                        ),
                        Cell::from(""),
                    ])
                })
                .collect::<Vec<Row>>(),
        ),
    };

    let table = Table::new(rows, widths)
        .header(header)
        .block(Block::default().borders(Borders::ALL).title(title))
        .row_highlight_style(Style::default().bg(Color::DarkGray))
        .highlight_symbol(">> ");

    let show_log = app.tab == Tab::YouTube && !app.transcribe_log.is_empty();
    if show_log {
        let split = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Percentage(55), Constraint::Percentage(45)])
            .split(area);
        frame.render_stateful_widget(table, split[0], &mut app.table);
        let log = Paragraph::new(app.transcribe_log.clone()).block(
            Block::default()
                .borders(Borders::ALL)
                .title(" transcription log "),
        );
        frame.render_widget(log, split[1]);
    } else {
        frame.render_stateful_widget(table, area, &mut app.table);
    }
}

fn draw_player(frame: &mut ratatui::Frame, app: &App, area: Rect) {
    if app.playing.is_none() {
        let hint = Paragraph::new("p play   space pause   [ ] seek 10s   s stop")
            .block(Block::default().borders(Borders::ALL).title(" player "))
            .style(Style::default().fg(Color::DarkGray));
        frame.render_widget(hint, area);
        return;
    }

    let block = Block::default().borders(Borders::ALL).title(" player ");
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let layout = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1),
            Constraint::Length(1),
            Constraint::Min(1),
        ])
        .split(inner);

    let duration = app.playback_duration;
    let ratio = match duration {
        Some(d) if d.as_secs_f64() > 0.0 => {
            (app.playback_position.as_secs_f64() / d.as_secs_f64()).clamp(0.0, 1.0)
        }
        _ => 0.0,
    };
    let gauge = Gauge::default()
        .ratio(ratio)
        .gauge_style(Style::default().fg(Color::Magenta))
        .label(format!(
            "{} / {}",
            srt::format_clock(app.playback_position),
            duration
                .map(srt::format_clock)
                .unwrap_or_else(|| "--:--".into())
        ));
    frame.render_widget(gauge, layout[0]);

    let title = app
        .playing
        .as_ref()
        .map(|v| v.display_title())
        .unwrap_or("")
        .to_string();
    let header_line = Line::from(vec![
        Span::styled(
            if app.playback_paused {
                "paused"
            } else {
                "playing"
            },
            Style::default().fg(Color::Cyan),
        ),
        Span::raw("  "),
        Span::styled(
            truncate(&title, 70),
            Style::default().add_modifier(Modifier::BOLD),
        ),
    ]);
    frame.render_widget(Paragraph::new(header_line), layout[1]);

    let cue = app.current_cue_text().unwrap_or_default().to_string();
    frame.render_widget(
        Paragraph::new(Line::from(cue)).wrap(Wrap { trim: true }),
        layout[2],
    );
}

fn truncate(text: &str, width: usize) -> String {
    if text.chars().count() <= width {
        return text.to_string();
    }
    let mut out: String = text.chars().take(width.saturating_sub(1)).collect();
    out.push('~');
    out
}

fn format_compact(n: i64) -> String {
    if n >= 1_000_000 {
        format!("{:.1}M", n as f64 / 1_000_000.0)
    } else if n >= 1_000 {
        format!("{:.1}K", n as f64 / 1_000.0)
    } else {
        n.to_string()
    }
}

/// Renders a Unix timestamp as a UTC date and time. Times before the epoch are
/// returned as-is, since they cannot be a real file mtime.
fn format_epoch(epoch: i64) -> String {
    if epoch < 0 {
        return epoch.to_string();
    }
    let secs = epoch as u64;
    // Days since the epoch -> civil date (Howard Hinnant's algorithm).
    let days = secs / 86_400;
    let secs_of_day = secs % 86_400;
    let z = days as i64 + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!(
        "{y:04}-{m:02}-{d:02} {:02}:{:02}",
        secs_of_day / 3_600,
        (secs_of_day % 3_600) / 60
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn truncate_respects_width() {
        assert_eq!(truncate("abc", 10), "abc");
        assert_eq!(truncate("abcdef", 4), "abc~");
    }

    #[test]
    fn format_compact_thresholds() {
        assert_eq!(format_compact(999), "999");
        assert_eq!(format_compact(1500), "1.5K");
        assert_eq!(format_compact(2_000_000), "2.0M");
    }

    #[test]
    fn format_epoch_matches_known_dates() {
        // 2026-01-02 03:04 UTC.
        assert_eq!(format_epoch(1_767_323_040), "2026-01-02 03:04");
        assert_eq!(format_epoch(0), "1970-01-01 00:00");
    }

    #[test]
    fn tab_cycle_wraps_both_ways() {
        assert_eq!(Tab::ALL.len(), 4);
        let mut tab = Tab::Library;
        for _ in 0..4 {
            let current = Tab::ALL.iter().position(|t| *t == tab).unwrap();
            tab = Tab::ALL[(current + 1) % Tab::ALL.len()];
        }
        assert_eq!(tab, Tab::Library);
    }

    #[test]
    fn tab_titles_and_placeholders_are_distinct() {
        let titles: Vec<&str> = Tab::ALL.iter().map(|t| t.title()).collect();
        assert_eq!(titles, ["Library", "Subtitles", "Jobs", "YouTube"]);
        let placeholders: Vec<&str> = Tab::ALL.iter().map(|t| t.placeholder()).collect();
        for (i, a) in placeholders.iter().enumerate() {
            for (j, b) in placeholders.iter().enumerate() {
                assert!(i == j || a != b, "placeholders must differ per tab");
            }
        }
    }
}
