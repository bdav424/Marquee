/* Wrapped so its internals stay private: these load as classic
   scripts and share one global scope with each other and the page. */
(function () {
  'use strict';

  /* Which theatre this page is showing, and how to change it.
   *
   * Shared by the grid and the board so they can never disagree about which
   * city is on screen.
   *
   * The fetcher builds one snapshot per configured market and an index listing
   * the ones that actually succeeded, so everything here reads local files — no
   * live call to Alamo, and switching cities works with the phone offline as
   * long as the cron has been round once.
   *
   * Choice comes from, in order: the ?m= query parameter, the last choice in
   * localStorage, the index's default. The query parameter wins so a link can
   * point at a specific city; the hash is left alone because the grid uses it
   * to deep-link a title.
   */

  const INDEX_URL = 'data/markets.json';
  const STORE_KEY = 'marquee.market';

  /* One market, always. If the index is missing — an old checkout, a cron that
     has never run — fall back to the file the display has always read, so a
     missing index degrades to the single-theatre behaviour rather than a blank
     page. */
  const FALLBACK = {
    default: null,
    markets: [{ slug: null, name: 'Winchester', file: 'marquee.json' }],
  };

  async function loadIndex() {
    try {
      const res = await fetch(INDEX_URL, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const index = await res.json();
      if (!index.markets || !index.markets.length) return FALLBACK;
      return index;
    } catch {
      return FALLBACK;
    }
  }

  function stored() {
    try {
      return localStorage.getItem(STORE_KEY);
    } catch {
      return null; // private browsing, or storage disabled
    }
  }

  function remember(slug) {
    try {
      localStorage.setItem(STORE_KEY, slug);
    } catch {
      /* the ?m= parameter still works, the choice just will not persist */
    }
  }

  function chosen(index) {
    const asked = new URLSearchParams(location.search).get('m');
    const known = slug => index.markets.find(m => m.slug === slug);
    // A remembered market that has since been removed from the config must not
    // strand the page on a file that no longer exists.
    return known(asked) || known(stored()) || known(index.default) ||
      index.markets[0];
  }

  function dataUrl(market) {
    return `data/${market.file}`;
  }

  /* The switcher itself: the theatre's name, and small text admitting it might
     be the wrong one. Deliberately quiet — this is one theatre's marquee and
     the picker is for a trip, not a national listings service. */
  function mountSwitcher(host, index, current) {
    host.replaceChildren();

    const name = document.createElement('span');
    name.className = 'market-name';
    name.textContent = current.name;
    host.appendChild(name);

    const toggle = document.createElement('button');
    toggle.className = 'market-swap';
    toggle.type = 'button';
    toggle.textContent = 'Not your theatre?';
    toggle.setAttribute('aria-expanded', 'false');
    host.appendChild(toggle);

    const menu = document.createElement('div');
    menu.className = 'market-menu';
    menu.hidden = true;
    host.appendChild(menu);

    for (const market of index.markets) {
      if (market.slug === null) continue; // the no-index fallback has no identity
      const item = document.createElement('a');
      item.className = 'market-item' + (market.slug === current.slug ? ' current' : '');
      // A real link, so it can be long-pressed, shared or bookmarked. The click
      // handler only exists to remember the choice on the way out.
      item.href = `?m=${encodeURIComponent(market.slug)}`;
      item.textContent = market.name;
      item.addEventListener('click', () => remember(market.slug));
      menu.appendChild(item);
    }

    // With one theatre configured the picker would be an empty gesture, so it
    // says what to do instead of showing a list of one.
    if (menu.childElementCount <= 1) {
      const note = document.createElement('p');
      note.className = 'market-note';
      note.textContent =
        'Only this one is configured. Add another to config/markets.toml and ' +
        'it will appear here after the next refresh.';
      menu.appendChild(note);
    }

    toggle.addEventListener('click', () => {
      menu.hidden = !menu.hidden;
      toggle.setAttribute('aria-expanded', String(!menu.hidden));
    });

    document.addEventListener('click', event => {
      if (!menu.hidden && !host.contains(event.target)) {
        menu.hidden = true;
        toggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  window.Market = { loadIndex, chosen, dataUrl, mountSwitcher, remember };
})();
