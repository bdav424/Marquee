/* Which look the display is wearing.
 *
 * Themes are variable overrides in themes.css, selected by a data-theme
 * attribute on <html>. Both surfaces read the same stored choice, so the grid
 * and the board never disagree about what the thing looks like.
 *
 * The attribute is set by a tiny inline script in each page's <head>, before
 * any stylesheet paints. Doing it here instead would show the default theme
 * for a frame and then swap, which on a dark-to-light change is a flash in
 * the face at ten at night.
 */
(function () {
  'use strict';

  const STORE_KEY = 'marquee.theme';

  const THEMES = [
    { id: 'marquee', name: 'Marquee', note: 'Warm bulbs and brass. The default.' },
    { id: '8bit', name: '8-bit', note: 'Console palette, hard edges, scanlines.' },
    { id: 'phosphor', name: 'Phosphor', note: 'Green CRT terminal.' },
    { id: 'newsprint', name: 'Newsprint', note: 'Local paper listings. Light.' },
  ];

  function current() {
    try {
      const stored = localStorage.getItem(STORE_KEY);
      return THEMES.some(t => t.id === stored) ? stored : 'marquee';
    } catch {
      return 'marquee';
    }
  }

  function apply(id) {
    // 'marquee' is the bare :root with no attribute, so it is removed rather
    // than set — otherwise the default would need its own duplicate block.
    if (id === 'marquee') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', id);
  }

  function set(id) {
    try {
      localStorage.setItem(STORE_KEY, id);
    } catch {
      /* applies to this page view only */
    }
    apply(id);
  }

  /* The picker, for the settings sheet. Returns a node the caller appends. */
  function picker(onChange) {
    const wrap = document.createElement('div');
    wrap.className = 'theme-picker';

    for (const theme of THEMES) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'theme-option' + (theme.id === current() ? ' on' : '');
      button.setAttribute('aria-pressed', String(theme.id === current()));

      // A swatch built from the theme's own tokens, so it cannot drift from
      // what choosing it actually does.
      const swatch = document.createElement('span');
      swatch.className = 'theme-swatch';
      swatch.dataset.theme = theme.id;
      button.appendChild(swatch);

      const text = document.createElement('span');
      text.className = 'theme-text';
      const name = document.createElement('span');
      name.className = 'theme-name';
      name.textContent = theme.name;
      const note = document.createElement('span');
      note.className = 'theme-note';
      note.textContent = theme.note;
      text.appendChild(name);
      text.appendChild(note);
      button.appendChild(text);

      button.addEventListener('click', () => {
        set(theme.id);
        if (onChange) onChange(theme.id);
      });
      wrap.appendChild(button);
    }
    return wrap;
  }

  window.Theme = { THEMES, current, apply, set, picker };
})();
