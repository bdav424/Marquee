/* Wrapped so its internals stay private: these load as classic
   scripts and share one global scope with each other and the page. */
(function () {
  'use strict';

  /* Your thresholds, applied in the browser.
   *
   * config/marquee.toml sets the fetcher's thresholds, and build.py bakes a
   * verdict into the snapshot. That verdict is one person's judgement. This
   * module lets a viewer set their own without touching the config, re-deriving
   * `flagged` from the per-category severity scores the payload already carries.
   *
   * Both surfaces import this, so the board and the grid can never disagree
   * about what your settings mean.
   *
   * Two rules survive from the original design, because they are what make the
   * signal trustworthy rather than decorative:
   *
   *   Unknown is not clean. A title whose rating reason could not be read has
   *   `null` severities, and null never satisfies a threshold. It stays visible
   *   and marked, and you have to opt in to treating unknown as flagged.
   *
   *   Hiding announces itself. `hide` mode removes titles from the list, but
   *   the page always says how many and offers them back in one tap. A filter
   *   you cannot see is indistinguishable from a theatre that is not showing
   *   the film.
   */

  const STORE_KEY = 'marquee.prefs';

  const CATEGORIES = ['violence', 'sexual', 'frightening', 'language', 'substance'];

  /* null means "never flags on this category", which is how language and
     substance ship — they display as chips and carry no weight. */
  const DEFAULTS = {
    thresholds: { violence: 3, sexual: 1, frightening: 2, language: null, substance: null },
    genreBackstop: true,   // Horror flags even with no readable reason
    flagUnknown: false,    // unknown stays visible and unweighted
    mode: 'dim',           // 'dim' | 'hide'
  };

  function clone(prefs) {
    return { ...prefs, thresholds: { ...prefs.thresholds } };
  }

  function defaults() {
    return clone(DEFAULTS);
  }

  function load() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
      if (!raw) return defaults();
      const prefs = defaults();
      for (const cat of CATEGORIES) {
        if (cat in (raw.thresholds || {})) {
          const v = raw.thresholds[cat];
          prefs.thresholds[cat] = v === null ? null : Math.max(1, Math.min(3, +v || 1));
        }
      }
      if (typeof raw.genreBackstop === 'boolean') prefs.genreBackstop = raw.genreBackstop;
      if (typeof raw.flagUnknown === 'boolean') prefs.flagUnknown = raw.flagUnknown;
      if (raw.mode === 'dim' || raw.mode === 'hide') prefs.mode = raw.mode;
      return prefs;
    } catch {
      return defaults();
    }
  }

  function save(prefs) {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(prefs));
    } catch {
      /* storage disabled: the settings apply to this page view and no further */
    }
  }

  function isDefault(prefs) {
    return JSON.stringify(prefs) === JSON.stringify(DEFAULTS);
  }

  /* Re-derive one title's verdict under these preferences.
   *
   * Returns the same shape build.py emits — {flagged, flags} — so callers can
   * treat a re-scored title exactly like a freshly built one. */
  function evaluate(title, prefs) {
    const flags = [];
    const severity = title.severity || {};

    for (const category of CATEGORIES) {
      const threshold = prefs.thresholds[category];
      if (threshold === null || threshold === undefined) continue;
      const score = severity[category];
      // null is unknown, and unknown never satisfies a threshold. Treating it
      // as 0 would quietly pass every unreadable title as clean.
      if (typeof score !== 'number') continue;
      if (score >= threshold) {
        const original = (title.flags || []).find(f => f.category === category);
        flags.push({
          category,
          score,
          threshold,
          reason: original ? original.reason : null,
          // The verbatim fragments come from the fetcher's parse and do not
          // depend on the threshold, so they carry over unchanged.
          evidence: original ? original.evidence : [],
        });
      }
    }

    if (prefs.genreBackstop) {
      const genre = (title.flags || []).find(f => f.category === 'genre');
      if (genre) flags.push(genre);
    }

    if (prefs.flagUnknown && !title.reason_parsed) {
      flags.push({
        category: 'unknown',
        score: null,
        threshold: null,
        reason: 'Rating reason could not be read, and you asked to flag those.',
        evidence: [],
      });
    }

    return { flagged: flags.length > 0, flags };
  }

  /* Apply preferences across a whole snapshot.
   *
   * Returns {shown, hidden}. In dim mode nothing is ever hidden and `hidden` is
   * empty; in hide mode the caller is expected to say how many went, and to
   * offer them back. */
  function apply(titles, prefs) {
    const scored = titles.map(title => ({ ...title, ...evaluate(title, prefs) }));
    if (prefs.mode !== 'hide') return { shown: scored, hidden: [] };
    return {
      shown: scored.filter(t => !t.flagged),
      hidden: scored.filter(t => t.flagged),
    };
  }

  window.Verdict = { defaults, load, save, isDefault, evaluate, apply, CATEGORIES };
})();
