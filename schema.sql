-- Bulgarian election video monitoring schema.
-- One DB per deployment; slug column lets us keep multiple elections side-by-side.

CREATE TABLE IF NOT EXISTS sections (
  sik          TEXT PRIMARY KEY,          -- 9-digit SIK code, e.g. 013300088
  slug         TEXT NOT NULL,             -- election slug, e.g. le20260420
  rik          TEXT,                      -- first 2 digits  (Регионална ИК / Областна)
  muni_code    TEXT,                      -- first 4 digits  (ОИК)
  region_name  TEXT,                      -- "Петрич", "Пазарджик", ...
  oik_page     TEXT,                      -- source HTML URL
  address      TEXT,                      -- full raw address from page
  town         TEXT,                      -- extracted town name (caps)
  town_type    TEXT CHECK (town_type IN ('village','town','city','unknown')),
  priority     INTEGER DEFAULT 0,         -- smaller = processed first (villages < towns < cities)
  created_at   TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS videos (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  sik              TEXT NOT NULL,
  slug             TEXT NOT NULL,
  tour             INTEGER NOT NULL DEFAULT 1,
  video_url        TEXT NOT NULL UNIQUE,
  video_type       TEXT CHECK (video_type IN ('device','live')),
  duration_sec     REAL,
  bytes            INTEGER,
  status           TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','downloading','downloaded',
                                     'transcribing','transcribed','analyzing',
                                     'analyzed','failed')),
  error            TEXT,
  discovered_at    TEXT DEFAULT CURRENT_TIMESTAMP,
  downloaded_at    TEXT,
  transcribed_at   TEXT,
  analyzed_at      TEXT,
  deleted_at       TEXT,                  -- when the mp4 was removed
  FOREIGN KEY (sik) REFERENCES sections(sik)
);

CREATE INDEX IF NOT EXISTS idx_videos_status      ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_sik         ON videos(sik);
CREATE INDEX IF NOT EXISTS idx_sections_priority  ON sections(priority);

CREATE TABLE IF NOT EXISTS transcripts (
  video_id      INTEGER PRIMARY KEY,
  full_text     TEXT,
  segments_json TEXT,                     -- JSON array [{start,end,text}]
  duration_sec  REAL,
  language      TEXT DEFAULT 'bg',
  model         TEXT,
  created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (video_id) REFERENCES videos(id)
);

CREATE TABLE IF NOT EXISTS findings (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id     INTEGER NOT NULL,
  severity     TEXT NOT NULL
               CHECK (severity IN ('info','low','medium','high','critical')),
  category     TEXT,                      -- tampering / disputes / intimidation / protocol / delay / other
  summary      TEXT NOT NULL,
  detail       TEXT,
  quote        TEXT,                      -- short transcript quote that triggered the finding
  timestamp_sec REAL,                     -- seconds into the video
  created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (video_id) REFERENCES videos(id)
);

CREATE INDEX IF NOT EXISTS idx_findings_video    ON findings(video_id);
CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity);
