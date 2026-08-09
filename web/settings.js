/* Wrapped so its internals stay private: these load as classic
   scripts and share one global scope with each other and the page. */
(function () {
  'use strict';

  /* The settings sheet.
   *
   * Everything here writes to the same preferences object verdict.js reads, so
   * changing a threshold re-scores the grid and the board identically. Nothing
   * is sent anywhere — this is one person's phone and one person's judgement,
   * which is the whole reason the thresholds moved out of the config file.
   */

  const LEVELS = [
    { value: null, label: 'Never' },
    { value: 1, label: 'Mild' },
    { value: 2, label: 'Moderate' },
    { value: 3, label: 'Severe' },
  ];

  const CATEGORY_LABELS = {
    violence: 'Violence',
    sexual: 'Sex / nudity',
    frightening: 'Frightening',
    language: 'Language',
    substance: 'Drugs / alcohol',
  };

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  /* One category: a row of buttons from Never to Severe. A slider was the other
     option, but four named steps say what they mean and a slider does not. */
  function levelRow(category, prefs, onChange) {
    const row = el('div', 'set-row');
    row.appendChild(el('span', 'set-label', CATEGORY_LABELS[category] || category));

    const group = el('div', 'set-levels');
    group.setAttribute('role', 'radiogroup');
    group.setAttribute('aria-label', CATEGORY_LABELS[category] || category);

    for (const level of LEVELS) {
      const button = el('button', 'set-level', level.label);
      button.type = 'button';
      button.setAttribute('role', 'radio');
      const selected = prefs.thresholds[category] === level.value;
      button.setAttribute('aria-checked', String(selected));
      button.classList.toggle('on', selected);
      button.addEventListener('click', () => {
        prefs.thresholds[category] = level.value;
        onChange();
      });
      group.appendChild(button);
    }

    row.appendChild(group);
    return row;
  }

  function toggleRow(label, help, get, set, onChange) {
    const row = el('div', 'set-row set-row-toggle');
    const text = el('div', 'set-text');
    text.appendChild(el('span', 'set-label', label));
    if (help) text.appendChild(el('span', 'set-help', help));
    row.appendChild(text);

    const button = el('button', 'set-switch');
    button.type = 'button';
    button.setAttribute('role', 'switch');
    const paint = () => {
      const on = get();
      button.setAttribute('aria-checked', String(on));
      button.classList.toggle('on', on);
      button.textContent = on ? 'On' : 'Off';
    };
    button.addEventListener('click', () => { set(!get()); onChange(); });
    paint();
    row.appendChild(button);
    return row;
  }

  function mountBody(host, prefs, apply) {
    const rerender = () => {
      Verdict.save(prefs);
      apply();
      mountBody(host, prefs, apply);   // repaint the controls' own state
    };

    host.replaceChildren();

    host.appendChild(el('p', 'set-intro',
      'Flag a title when its rating reason reaches this level. These are ' +
      'yours, stored on this device, and they change what you see on both the ' +
      'grid and the board.'));

    for (const category of Verdict.CATEGORIES) {
      host.appendChild(levelRow(category, prefs, rerender));
    }

    host.appendChild(el('hr', 'set-rule'));

    host.appendChild(toggleRow(
      'Flag anything filed as Horror',
      'Works even when no rating reason can be read, which is most repertory ' +
      'programming.',
      () => prefs.genreBackstop,
      v => { prefs.genreBackstop = v; },
      rerender));

    host.appendChild(toggleRow(
      'Flag unreadable ratings',
      'Off by default. Unknown is not the same as bad — it is shown at full ' +
      'weight and marked with a question mark.',
      () => prefs.flagUnknown,
      v => { prefs.flagUnknown = v; },
      rerender));

    host.appendChild(el('hr', 'set-rule'));

    host.appendChild(toggleRow(
      'Hide flagged titles instead of dimming',
      'The count of what is hidden always stays on screen, with a tap to show ' +
      'them. A filter you cannot see looks the same as a film not playing.',
      () => prefs.mode === 'hide',
      v => { prefs.mode = v ? 'hide' : 'dim'; },
      rerender));

    host.appendChild(el('hr', 'set-rule'));
    host.appendChild(el('span', 'set-label', 'Theme'));
    // Repaints on change so the picker's own highlight follows the choice.
    host.appendChild(Theme.picker(() => mountBody(host, prefs, apply)));

    const reset = el('button', 'set-reset', 'Reset to defaults');
    reset.type = 'button';
    reset.disabled = Verdict.isDefault(prefs);
    reset.addEventListener('click', () => {
      Object.assign(prefs, Verdict.defaults());
      rerender();
    });
    host.appendChild(reset);
  }

  /* Wire the settings sheet to its open/close controls. `apply` is called
     whenever anything changes, and is what re-renders the caller's view. */
  function mountSettings({ openButton, sheet, body, closeButton, prefs, apply }) {
    const setOpen = open => {
      sheet.hidden = !open;
      openButton.setAttribute('aria-expanded', String(open));
      if (open) mountBody(body, prefs, apply);
    };

    openButton.addEventListener('click', () => setOpen(sheet.hidden));
    if (closeButton) closeButton.addEventListener('click', () => setOpen(false));
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && !sheet.hidden) setOpen(false);
    });
    return { setOpen };
  }

  window.Settings = { mountSettings };
})();
