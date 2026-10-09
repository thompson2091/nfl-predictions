// Saved picks survive a reload, a second tab, and a restore.
//
// "My picks disappear when you deploy" came from three places: a tab with an
// older list overwrote storage on every render, picks past last week lost
// their result, and each address keeps its own storage. This drives the
// first and the restore path in a real browser. It reaches into the app's
// own functions (`v3SaveSlip`, `v3DropSaved`, `v3RestorePicks`) rather than
// clicking, because what is under test is the storage, not the slip's
// layout — the workflows in the config click through the UI.

/** @type {import("qa-agent").QAModule} */
export default {
  id: "saved-picks",
  title: "Saved picks persist",
  description: "A saved pick survives reload; a stale tab cannot wipe or resurrect one; restore merges.",
  matrix: { viewports: "primary", locales: "default", roles: "default", browsers: "primary" },
  scopes: ["full", "smoke", "functional"],

  plan(ctx) {
    const first = ctx.inventory.pages[0];
    return first ? [{ id: "saved-picks:site", moduleId: "saved-picks",
      title: "Saved picks persist across reload and tabs", url: first.url,
      route: first.route, risk: 9 }] : [];
  },

  async run(task, ctx) {
    const page = ctx.page;
    const fail = async (title, actual) => ctx.report({
      ruleId: "saved-picks", title, category: "functional", severity: "high",
      kind: "bug", source: "automated",
      expected: "Saved picks persist and merge across tabs.", actual,
      signature: "saved-picks:" + title });

    await page.goto(task.url);
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    const saved = await page.evaluate(() => {
      V.tab = 'props'; render();
      const row = rowsFor(V.market, null).find(r => r.priced !== false);
      if (!row) return 'no row';
      V.picks = {}; V.picks[row.id] = 1; render();
      v3SaveSlip(); render();
      return V.saved.length;
    });
    if (saved !== 1) return fail("A pick could not be saved", String(saved));

    await page.reload();
    const after = await page.evaluate(() => V.saved.length);
    if (after !== 1) return fail("A saved pick did not survive a reload", String(after));
    ctx.check("saved pick survives reload", "passed");

    // A second tab deletes it; the first, still holding it, redraws.
    const other = await page.context().newPage();
    await other.goto(task.url);
    await other.evaluate(() => { v3DropSaved(V.saved[0].id); render(); });
    const resurrected = await page.evaluate(() => { render(); return V.saved.length; });
    if (resurrected !== 0) {
      await other.close();
      return fail("A stale tab brought back a deleted pick", String(resurrected));
    }
    ctx.check("a stale tab cannot resurrect a deleted pick", "passed");

    // Save again in tab two; tab one, with an empty list, must not wipe it.
    const two = await other.evaluate(() => {
      const row = rowsFor(V.market, null).find(r => r.priced !== false);
      V.picks = {}; V.picks[row.id] = 1; V.stake = 11; render();
      v3SaveSlip(); render(); return V.saved.length;
    });
    const kept = await page.evaluate(() => { V.saved = []; render(); return V.saved.length; });
    await other.close();
    if (two !== 1 || kept !== 1) {
      return fail("A stale tab wiped a pick saved in another tab",
                  "other tab " + two + ", after stale render " + kept);
    }
    ctx.check("a stale tab cannot wipe a pick saved elsewhere", "passed");

    // TWO TABS OPEN, FILTERS TAPPED: neither may hang. 20261009.v1 shipped a
    // storage listener that redrew on every write, and every redraw writes,
    // so two tabs redrew each other forever after the second tap on Props.
    const third = await page.context().newPage();
    await third.goto(task.url);
    await page.evaluate(() => { V.tab = 'props'; render(); });
    for (const sel of ['[data-v3filter="short"]', '[data-v3filter="gap"]',
                       '[data-v3mkt="rec"]', '[data-v3filter="all"]']) {
      try { await page.click(sel, { timeout: 5000 }); }
      catch (e) {
        await third.close();
        return fail("Props filters hang with a second tab open", sel + ": " + String(e).slice(0, 120));
      }
    }
    await third.close();
    ctx.check("filters respond with a second tab open", "passed");

    // Copy, clear, restore.
    const restored = await page.evaluate(() => {
      const text = JSON.stringify({picksix: 1, saved: V.saved});
      localStorage.clear(); V.saved = []; V.savedGone = [];
      v3RestorePicks(text); render();
      return V.saved.length + '|' + V.restoreMsg;
    });
    if (!restored.startsWith('1|')) return fail("Restore did not bring the picks back", restored);
    ctx.check("restore merges a copied list", "passed");
  },
};
