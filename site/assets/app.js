"use strict";
/* Walletbrief: rendert de nieuwsbrief uit data/items.json en data/config.json.
   Alle tekst uit bronnen wordt ge-escaped; links worden alleen als http(s) toegelaten. */
(function () {
  const LEVELS = { hoog: 3, middel: 2, laag: 1, geen: 0 };
  const TYPE_LABEL = {
    feed: "RSS/Atom", html: "Webpagina", json: "API (JSON)", sparql: "SPARQL (EUR-Lex)",
    sru: "SRU (KOOP)", pagewatch: "Paginawijzigingen",
  };
  const NL_CATEGORIES = new Set(["nl-overheid", "nl-moza"]);
  const PAGE_SIZE = 50;
  const NEW_DAYS = 7;

  const state = {
    items: [], config: null, generated: null, byWeek: new Map(), editions: [],
    editionKey: null, archiveLimit: PAGE_SIZE, preview: Boolean(window.NIEUWSBRIEF_DATA),
  };
  const $ = (selector) => document.querySelector(selector);

  // --- Hulpfuncties -----------------------------------------------------------

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function safeUrl(value) {
    try {
      const url = new URL(value, location.href);
      return url.protocol === "https:" || url.protocol === "http:" ? url.href : "#";
    } catch (e) {
      return "#";
    }
  }

  function link(url, text) {
    return `<a href="${esc(safeUrl(url))}" target="_blank" rel="noopener">${esc(text)}</a>`;
  }

  function parseDay(value) {
    const [y, m, d] = String(value).slice(0, 10).split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d));
  }

  function isoWeek(date) {
    const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
    const day = d.getUTCDay() || 7;
    d.setUTCDate(d.getUTCDate() + 4 - day);
    const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    return { year: d.getUTCFullYear(), week: Math.ceil(((d - yearStart) / 86400000 + 1) / 7) };
  }

  function weekKey(day) {
    const w = isoWeek(parseDay(day));
    return `${w.year}-${String(w.week).padStart(2, "0")}`;
  }

  function weekMonday(key) {
    const [year, week] = key.split("-").map(Number);
    const jan4 = new Date(Date.UTC(year, 0, 4));
    const monday = new Date(jan4);
    monday.setUTCDate(jan4.getUTCDate() - (jan4.getUTCDay() || 7) + 1 + (week - 1) * 7);
    return monday;
  }

  const fmtDay = new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const fmtLong = new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  const fmtDayMonth = new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "long", timeZone: "UTC" });
  const fmtStamp = new Intl.DateTimeFormat("nl-NL", {
    day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Amsterdam",
  });

  function weekInfo(key) {
    const monday = weekMonday(key);
    const sunday = new Date(monday);
    sunday.setUTCDate(monday.getUTCDate() + 6);
    let range;
    if (monday.getUTCFullYear() !== sunday.getUTCFullYear()) range = `${fmtLong.format(monday)} – ${fmtLong.format(sunday)}`;
    else if (monday.getUTCMonth() === sunday.getUTCMonth()) range = `${monday.getUTCDate()} – ${fmtLong.format(sunday)}`;
    else range = `${fmtDayMonth.format(monday)} – ${fmtLong.format(sunday)}`;
    const [year, week] = key.split("-").map(Number);
    return { year, week, range };
  }

  function formatDate(day) {
    return day ? fmtDay.format(parseDay(day)) : "";
  }

  function level(item) {
    return (item.ai && item.ai.moza_relevantie) || item.moza_level || "laag";
  }

  function rank(a, b) {
    return (LEVELS[level(b)] - LEVELS[level(a)]) || ((b.score || 0) - (a.score || 0)) || b.date.localeCompare(a.date);
  }

  function isNL(item) {
    return NL_CATEGORIES.has(item.category);
  }

  function isNew(item) {
    if (!state.generated || !item.first_seen) return false;
    return (new Date(state.generated) - new Date(item.first_seen)) / 86400000 < NEW_DAYS;
  }

  function topic(id) {
    return state.config.onderwerpen.find((t) => t.id === id) || { id, naam: id, kort: id };
  }

  function theme(id) {
    return state.config.moza_themas.find((t) => t.id === id) || { id, naam: id, uitleg: "", moza_onderdelen: [] };
  }

  function categoryName(id) {
    return (state.config.categorieen || {})[id] || id;
  }

  function normalize(text) {
    return String(text || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  // --- Onderdelen --------------------------------------------------------------

  const SECTIONS = [
    {
      id: "ebw", titel: "European Business Wallet",
      intro: "Wetgeving, beleid, uitvoeringsregels en pilots rond de business wallet voor bedrijven en overheden.",
      test: (i) => !isNL(i) && i.topics.includes("ebw"),
    },
    {
      id: "eudi", titel: "EUDI Wallet & eIDAS",
      intro: "De Europese identiteitswallet voor burgers: uitvoeringshandelingen, het technische raamwerk en de uitrol.",
      test: (i) => !isNL(i) && !i.topics.includes("ebw") && i.topics.includes("eudi"),
    },
    {
      id: "trust", titel: "Vertrouwensdiensten & standaarden",
      intro: "Normen en regels voor handtekeningen, zegels en aangetekende elektronische bezorging (QERDS).",
      test: (i) => !isNL(i) && !i.topics.includes("ebw") && !i.topics.includes("eudi"),
    },
    {
      id: "nl", titel: "Nederland",
      intro: "Kamerstukken, Rijksoverheid, de NL Wallet en MijnOverheid Zakelijk zelf.",
      test: isNL,
    },
  ];

  function renderItem(item) {
    const lvl = level(item);
    const chips = item.topics.map((t) => `<span class="chip topic">${esc(topic(t).kort)}</span>`).join("");
    const summary = item.ai ? item.ai.samenvatting : item.summary;
    const themes = (item.moza || []).map((m) => theme(m.thema).naam);
    const note = item.ai && item.ai.moza_toelichting;
    let moza = "";
    if (lvl !== "geen" && (themes.length || note)) {
      moza = `<div class="item-moza"><span class="label">MOZa-lens</span>`
        + `<span class="chip level-${esc(lvl)}">${esc(lvl)}</span>`
        + (themes.length ? `<span>${esc(themes.join(" · "))}</span>` : "")
        + (note ? `<span class="note">${esc(note)}</span>` : "")
        + `</div>`;
    }
    const original = item.ai && item.summary
      ? `<details><summary>Oorspronkelijke tekst</summary><p>${esc(item.summary)}</p></details>` : "";
    const also = (item.also || []).length
      ? `<p class="also">Ook gemeld door ${item.also.map((a) => link(a.url, a.source_name)).join(", ")}</p>` : "";
    return `<article class="item" id="item-${esc(item.id)}">
      <div class="item-meta"><span>${esc(item.source_name)}</span>
        <time datetime="${esc(item.date)}" title="${item.published ? "Publicatiedatum" : "Datum waarop het bericht is gevonden"}">${item.published ? "" : "gevonden "}${esc(formatDate(item.date))}</time>${chips}
        ${isNew(item) ? '<span class="chip nieuw">nieuw</span>' : ""}
        ${item.ai ? '<span class="chip ai" title="Samenvatting en MOZa-duiding gemaakt met AI; controleer de bron">AI</span>' : ""}
      </div>
      <h4>${link(item.url, item.title)}</h4>
      ${summary ? `<p class="item-summary">${esc(summary)}</p>` : ""}
      ${item.fragment && !item.ai ? `<p class="item-fragment"><span class="label">Uit de tekst</span> ${esc(item.fragment)}</p>` : ""}
      ${moza}${original}${also}
    </article>`;
  }

  function editionItems(key) {
    return (state.byWeek.get(key) || []).slice().sort(rank);
  }

  function lensGroups(items) {
    return state.config.moza_themas
      .map((t) => ({ theme: t, items: items.filter((i) => (i.moza || []).some((m) => m.thema === t.id)) }))
      .filter((g) => g.items.length);
  }

  function renderEdition() {
    const key = state.editionKey;
    const items = editionItems(key);
    const info = weekInfo(key);
    const index = state.editions.indexOf(key);
    const high = items.filter((i) => level(i) === "hoog").length;
    const sources = new Set(items.map((i) => i.source)).size;
    const running = key === state.currentWeek;

    const options = state.editions.map((k) => {
      const w = weekInfo(k);
      return `<option value="${esc(k)}"${k === key ? " selected" : ""}>Week ${w.week} · ${esc(w.range)} (${state.byWeek.get(k).length})</option>`;
    }).join("");

    let html = `<header class="edition-head">
      <p class="eyebrow">Editie week ${info.week} · ${info.year}${running ? " · lopende week" : ""}</p>
      <h2>${esc(info.range)}</h2>
      <p class="edition-stats"><strong>${items.length}</strong> ${items.length === 1 ? "bericht" : "berichten"} uit
        <strong>${sources}</strong> ${sources === 1 ? "bron" : "bronnen"}, waarvan <strong>${high}</strong> met hoge relevantie voor MOZa</p>
      <div class="toolbar no-print">
        <button type="button" id="vorige" ${index >= state.editions.length - 1 ? "disabled" : ""} aria-label="Vorige editie">‹ Vorige</button>
        <label class="visually-hidden" for="kies-editie">Kies een editie</label>
        <select id="kies-editie">${options}</select>
        <button type="button" id="volgende" ${index <= 0 ? "disabled" : ""} aria-label="Volgende editie">Volgende ›</button>
        <button type="button" class="primary" id="kopieer">Kopieer voor e-mail</button>
        ${state.preview ? "" : '<button type="button" id="download">Download HTML</button><button type="button" id="afdrukken">Afdrukken / PDF</button>'}
      </div>
      <p class="toast no-print" id="melding" role="status"></p>
    </header>`;

    if (!items.length) {
      html += `<p class="empty">In deze week zijn geen relevante berichten gevonden.</p>`;
    } else {
      const top = items.slice(0, 5);
      html += `<section class="section"><h3>In het kort</h3><ol class="brief">${top.map((i) => `
        <li><span class="chip level-${esc(level(i))}">${esc(level(i))}</span>
          <span><a href="#item-${esc(i.id)}" data-scroll="item-${esc(i.id)}">${esc(i.title)}</a>
          <span class="section-intro"> · ${esc(i.source_name)}</span></span></li>`).join("")}</ol></section>`;

      const groups = lensGroups(items);
      if (groups.length) {
        html += `<section class="section lens" aria-labelledby="lens-kop">
          <h3 id="lens-kop">Wat betekent dit voor MijnOverheid Zakelijk?</h3>
          <p class="section-intro">Het nieuws van deze week per thema waarop het MOZa raakt.</p>
          ${groups.map((g) => `<div class="lens-theme">
            <h4>${esc(g.theme.naam)}</h4>
            ${(g.theme.moza_onderdelen || []).length ? `<span class="parts">Raakt: ${esc(g.theme.moza_onderdelen.join(", "))}</span>` : ""}
            <p>${esc(g.theme.uitleg)}</p>
            <ul>${g.items.map((i) => `<li><a href="#item-${esc(i.id)}" data-scroll="item-${esc(i.id)}">${esc(i.title)}</a>
              ${i.ai && i.ai.moza_toelichting ? ` – ${esc(i.ai.moza_toelichting)}` : ""}</li>`).join("")}</ul>
          </div>`).join("")}
        </section>`;
      }

      for (const section of SECTIONS) {
        const list = items.filter(section.test);
        if (!list.length) continue;
        html += `<section class="section" aria-labelledby="sectie-${section.id}">
          <h3 id="sectie-${section.id}">${esc(section.titel)} <span class="count">${list.length}</span></h3>
          <p class="section-intro">${esc(section.intro)}</p>
          <div class="items">${list.map(renderItem).join("")}</div>
        </section>`;
      }
    }
    $("#editie").innerHTML = html;
    renderRail(items);

    $("#kies-editie").addEventListener("change", (e) => selectEdition(e.target.value));
    $("#vorige").addEventListener("click", () => selectEdition(state.editions[index + 1]));
    $("#volgende").addEventListener("click", () => selectEdition(state.editions[index - 1]));
    $("#kopieer").addEventListener("click", copyEmail);
    if (!state.preview) {
      $("#download").addEventListener("click", downloadHtml);
      $("#afdrukken").addEventListener("click", () => window.print());
    }
  }

  function renderRail(items) {
    const counts = {
      ebw: items.filter((i) => i.topics.includes("ebw")).length,
      eudi: items.filter((i) => i.topics.includes("eudi")).length,
    };
    const statuses = (state.config.bronnen || []).filter((b) => b.actief);
    const failing = statuses.filter((b) => b.ok === false);
    const ebw = (state.config.achtergrond.dossiers || []).find((d) => d.id === "ebw");
    $("#zijkolom").innerHTML = `
      <section aria-labelledby="cijfers-kop">
        <h3 id="cijfers-kop">Deze editie</h3>
        <dl class="figures">
          <div><dt>berichten</dt><dd>${items.length}</dd></div>
          <div><dt>hoog voor MOZa</dt><dd>${items.filter((i) => level(i) === "hoog").length}</dd></div>
          <div><dt>over de EBW</dt><dd>${counts.ebw}</dd></div>
          <div><dt>over de EUDI Wallet</dt><dd>${counts.eudi}</dd></div>
        </dl>
      </section>
      ${ebw ? `<section aria-labelledby="dossier-kop">
        <h3 id="dossier-kop">Dossier ${esc(ebw.titel)}</h3>
        <p class="mono">${esc(ebw.subtitel)}</p>
        <p>${esc(ebw.status)}</p>
        ${renderTimeline(ebw.mijlpalen.slice(-4), true)}
        <a href="#dossiers">Alle stappen en de MOZa-kernvragen</a>
      </section>` : ""}
      <section aria-labelledby="bronnen-kop">
        <h3 id="bronnen-kop">Bronnen</h3>
        <p>${statuses.length - failing.length} van ${statuses.length} bronnen werkten bij de laatste controle.</p>
        ${failing.length ? `<p class="mono">Niet bereikbaar: ${esc(failing.map((b) => b.naam).join("; "))}</p>` : ""}
        <a href="#bronnen">Overzicht van alle bronnen</a>
      </section>`;
  }

  function renderTimeline(steps, compact) {
    return `<ol class="timeline${compact ? " compact" : ""}">${steps.map((s) => `
      <li class="${s.verwacht ? "expected" : ""}">
        <span class="when">${esc(s.datum ? formatDate(String(s.datum)) : s.datum_tekst)}</span>
        <span class="what">${esc(s.tekst)}${s.bron ? ` ${link(s.bron, "bron")}` : ""}</span>
      </li>`).join("")}</ol>`;
  }

  // --- Archief -------------------------------------------------------------------

  function setupArchive() {
    const topicSelect = $("#filter-onderwerp");
    for (const t of state.config.onderwerpen) topicSelect.insertAdjacentHTML("beforeend", `<option value="${esc(t.id)}">${esc(t.naam)}</option>`);
    const categorySelect = $("#filter-categorie");
    for (const [id, naam] of Object.entries(state.config.categorieen || {})) {
      categorySelect.insertAdjacentHTML("beforeend", `<option value="${esc(id)}">${esc(naam)}</option>`);
    }
    for (const id of ["zoek", "filter-onderwerp", "filter-categorie", "filter-moza"]) {
      $(`#${id}`).addEventListener("input", () => { state.archiveLimit = PAGE_SIZE; renderArchive(); });
    }
    $("#meer-resultaten").addEventListener("click", () => { state.archiveLimit += PAGE_SIZE; renderArchive(); });
  }

  function renderArchive() {
    const query = normalize($("#zoek").value).split(/\s+/).filter(Boolean);
    const topicFilter = $("#filter-onderwerp").value;
    const categoryFilter = $("#filter-categorie").value;
    const mozaFilter = $("#filter-moza").value;
    const results = state.items.filter((i) => {
      if (topicFilter && !i.topics.includes(topicFilter)) return false;
      if (categoryFilter && i.category !== categoryFilter) return false;
      if (mozaFilter === "hoog" && level(i) !== "hoog") return false;
      if (mozaFilter === "middel" && LEVELS[level(i)] < LEVELS.middel) return false;
      if (!query.length) return true;
      const haystack = normalize([i.title, i.summary, i.source_name, i.ai && i.ai.samenvatting].join(" "));
      return query.every((q) => haystack.includes(q));
    }).sort((a, b) => b.date.localeCompare(a.date) || rank(a, b));
    $("#aantal-resultaten").textContent = `${results.length} ${results.length === 1 ? "bericht" : "berichten"}`;
    $("#archief-lijst").innerHTML = results.slice(0, state.archiveLimit).map(renderItem).join("")
      || `<p class="empty">Geen berichten gevonden. Probeer een ander zoekwoord of minder filters.</p>`;
    $("#meer-resultaten").hidden = results.length <= state.archiveLimit;
  }

  // --- Dossiers ------------------------------------------------------------------

  function renderDossiers() {
    const bg = state.config.achtergrond;
    const moza = bg.moza;
    $("#dossiers-inhoud").innerHTML = `
      <div class="dossiers">${(bg.dossiers || []).map((d) => `
        <section class="dossier" aria-labelledby="dossier-${esc(d.id)}">
          <p class="eyebrow">Dossier</p>
          <h2 id="dossier-${esc(d.id)}">${esc(d.titel)}</h2>
          <p class="code">${esc(d.subtitel)}</p>
          <p class="status">${esc(d.status)}</p>
          ${renderTimeline(d.mijlpalen, false)}
        </section>`).join("")}
      </div>
      <section class="moza-block lens" aria-labelledby="moza-kop">
        <h2 id="moza-kop">${esc(moza.titel)}</h2>
        <p class="intro">${esc(moza.inleiding)}</p>
        <dl class="questions">${moza.kernvragen.map((v) => `<div><dt>${esc(v.vraag)}</dt>
          <dd>${esc(v.tekst)}${v.bron ? ` ${link(v.bron, "bron")}` : ""}</dd></div>`).join("")}</dl>
        <p class="section-intro">Achtergrond: ${moza.bronnen.map((b) => link(b.url, b.naam)).join(" · ")}</p>
      </section>
      <section class="section" aria-labelledby="themas-kop">
        <h3 id="themas-kop">Zo duidt de Walletbrief berichten voor MOZa</h3>
        <p class="section-intro">Elk bericht wordt op trefwoorden ingedeeld in deze thema's. Ze bepalen de MOZa-lens in de nieuwsbrief.</p>
        <div class="themes">${state.config.moza_themas.map((t) => `<article>
          <h4>${esc(t.naam)}</h4><p>${esc(t.uitleg)}</p></article>`).join("")}</div>
      </section>
      <p class="section-intro">Laatst handmatig bijgewerkt: ${esc(bg.bijgewerkt ? formatDate(String(bg.bijgewerkt)) : "onbekend")}.</p>`;
  }

  // --- Bronnen -------------------------------------------------------------------

  function statusChip(source) {
    if (!source.actief) return '<span class="chip status-uit">uit</span>';
    if (source.ok === true) return '<span class="chip status-ok">werkt</span>';
    if (source.ok === false) return '<span class="chip status-fout">fout</span>';
    return '<span class="chip status-nog">nog niet</span>';
  }

  function renderSources() {
    const sources = state.config.bronnen || [];
    const active = sources.filter((s) => s.actief);
    const working = active.filter((s) => s.ok).length;
    const repo = state.config.repository;
    const editLink = repo
      ? ` ${link(`https://github.com/${repo}/blob/${state.config.branch || "main"}/config/bronnen.yaml`, "config/bronnen.yaml")}`
      : " config/bronnen.yaml";
    const groups = Object.keys(state.config.categorieen || {});
    const rows = groups.map((cat) => {
      const list = sources.filter((s) => s.categorie === cat);
      if (!list.length) return "";
      return `<tr class="category-head"><td colspan="5">${esc(categoryName(cat))}</td></tr>` + list.map((s) => `
        <tr>
          <td>${link(s.site || s.url, s.naam)}<div class="desc">${esc(s.toelichting)}</div>
            ${s.ok === false && s.fout ? `<div class="err">${esc(s.fout)}</div>` : ""}</td>
          <td>${statusChip(s)}</td>
          <td>${esc(TYPE_LABEL[s.type] || s.type)}</td>
          <td class="num">${s.relevant || 0} / ${s.gevonden || 0}</td>
          <td class="num">${s.laatst_gecontroleerd ? esc(fmtStamp.format(new Date(s.laatst_gecontroleerd))) : "–"}</td>
        </tr>`).join("");
    }).join("");
    $("#bronnen-inhoud").innerHTML = `
      <div class="sheet" style="display:grid;gap:16px">
        <div class="section" style="padding-top:0">
          <h2>Bronnen</h2>
          <p class="section-intro">${working} van ${active.length} actieve bronnen werkten bij de laatste controle.
            Bronnen toevoegen of aanpassen doe je in${editLink}; de toelichting per bron staat in BRONNEN.md.</p>
        </div>
        <div class="table-wrap"><table>
          <thead><tr><th scope="col">Bron</th><th scope="col">Status</th><th scope="col">Methode</th>
            <th scope="col">Relevant / gevonden</th><th scope="col">Laatst gecontroleerd</th></tr></thead>
          <tbody>${rows}</tbody>
        </table></div>
      </div>`;
  }

  // --- E-mail, download, afdrukken -----------------------------------------------

  const MAIL = {
    font: "font-family:'Segoe UI',Arial,sans-serif;",
    ink: "#15212a", muted: "#4b5965", accent: "#0a5d69", lens: "#9a5200", lensBg: "#fbf1e2", rule: "#d6dee3",
  };

  function editionUrl(key) {
    if (state.preview) return "";
    return `${location.href.split("#")[0]}#editie-${key}`;
  }

  function emailHtml(key) {
    const items = editionItems(key);
    const info = weekInfo(key);
    const url = editionUrl(key);
    const p = (style, inner) => `<p style="margin:0 0 8px;${style}">${inner}</p>`;
    const mailItem = (i) => {
      const summary = i.ai ? i.ai.samenvatting : i.summary;
      const themes = (i.moza || []).map((m) => theme(m.thema).naam).join(" · ");
      const note = i.ai && i.ai.moza_toelichting;
      return `<div style="padding:10px 0;border-top:1px solid ${MAIL.rule}">`
        + p(`font-size:12px;color:${MAIL.muted}`, `${esc(i.source_name)} · ${esc(formatDate(i.date))}`)
        + p("font-size:16px;font-weight:bold", `<a href="${esc(safeUrl(i.url))}" style="color:${MAIL.ink}">${esc(i.title)}</a>`)
        + (summary ? p("", esc(summary)) : "")
        + (themes || note ? p(`font-size:13px;color:${MAIL.lens}`, `<b>MOZa-lens (${esc(level(i))}):</b> ${esc([themes, note].filter(Boolean).join(" – "))}`) : "")
        + `</div>`;
    };
    let html = `<div style="${MAIL.font}max-width:680px;color:${MAIL.ink};font-size:15px;line-height:1.5">`;
    html += p(`font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:${MAIL.muted}`, `Walletbrief · week ${info.week} · ${esc(info.range)}`);
    html += `<h1 style="margin:0 0 12px;font-size:24px;color:${MAIL.ink}">EUDI Wallet &amp; European Business Wallet</h1>`;
    html += p("", `${items.length} berichten uit officiële bronnen, waarvan ${items.filter((i) => level(i) === "hoog").length} met hoge relevantie voor MijnOverheid Zakelijk.`);
    if (items.length) {
      html += `<h2 style="font-size:18px;margin:20px 0 8px">In het kort</h2><ol style="margin:0;padding-left:20px">`
        + items.slice(0, 5).map((i) => `<li style="margin-bottom:4px"><a href="${esc(safeUrl(i.url))}" style="color:${MAIL.accent}">${esc(i.title)}</a> <span style="color:${MAIL.muted}">(${esc(i.source_name)})</span></li>`).join("")
        + `</ol>`;
      const groups = lensGroups(items);
      if (groups.length) {
        html += `<div style="background:${MAIL.lensBg};padding:14px 16px;margin:20px 0;border:1px solid #ecd2ad">`
          + `<h2 style="font-size:18px;margin:0 0 8px;color:${MAIL.lens}">Wat betekent dit voor MijnOverheid Zakelijk?</h2>`
          + groups.map((g) => p("font-size:14px", `<b>${esc(g.theme.naam)}</b> (${esc((g.theme.moza_onderdelen || []).join(", "))}): `
            + g.items.map((i) => esc(i.title)).join("; "))).join("")
          + `</div>`;
      }
      for (const section of SECTIONS) {
        const list = items.filter(section.test);
        if (!list.length) continue;
        html += `<h2 style="font-size:18px;margin:20px 0 4px">${esc(section.titel)}</h2>` + list.map(mailItem).join("");
      }
    }
    html += p(`font-size:12px;color:${MAIL.muted};margin-top:20px`, `Automatisch samengesteld uit officiële bronnen. Controleer de originele bron voor besluitvorming.`
      + (url ? ` Online lezen en archief: <a href="${esc(url)}" style="color:${MAIL.accent}">${esc(url)}</a>` : ""));
    return html + `</div>`;
  }

  function emailText(key) {
    const items = editionItems(key);
    const info = weekInfo(key);
    const lines = [`Walletbrief week ${info.week} (${info.range})`, ""];
    for (const section of SECTIONS) {
      const list = items.filter(section.test);
      if (!list.length) continue;
      lines.push(section.titel.toUpperCase());
      for (const i of list) {
        lines.push(`- ${i.title} (${i.source_name}, ${formatDate(i.date)})`, `  ${safeUrl(i.url)}`);
        if (i.ai && i.ai.moza_toelichting) lines.push(`  MOZa: ${i.ai.moza_toelichting}`);
      }
      lines.push("");
    }
    const url = editionUrl(key);
    if (url) lines.push(`Online lezen: ${url}`);
    return lines.join("\n");
  }

  function showMessage(text) {
    const el = $("#melding");
    if (el) el.textContent = text;
  }

  async function copyEmail() {
    const html = emailHtml(state.editionKey);
    try {
      if (!window.ClipboardItem || !navigator.clipboard || !navigator.clipboard.write) throw new Error("geen ClipboardItem");
      await navigator.clipboard.write([new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([emailText(state.editionKey)], { type: "text/plain" }),
      })]);
      showMessage("Gekopieerd. Plak de nieuwsbrief in een nieuwe e-mail.");
    } catch (e) {
      const holder = document.createElement("div");
      holder.innerHTML = html;
      holder.style.position = "fixed";
      holder.style.left = "-10000px";
      document.body.appendChild(holder);
      const range = document.createRange();
      range.selectNodeContents(holder);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      let ok = false;
      try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
      selection.removeAllRanges();
      holder.remove();
      let failed = "Kopiëren lukte niet in deze browser. Gebruik 'Download HTML' en open het bestand in je mailprogramma.";
      if (state.preview) failed = "Kopiëren lukte niet in deze voorbeeldweergave. Op de gepubliceerde site werkt het wel.";
      showMessage(ok ? "Gekopieerd. Plak de nieuwsbrief in een nieuwe e-mail." : failed);
    }
  }

  function downloadHtml() {
    const info = weekInfo(state.editionKey);
    const doc = `<!doctype html><html lang="nl"><head><meta charset="utf-8"><title>Walletbrief week ${info.week} ${info.year}</title></head>`
      + `<body style="margin:24px">${emailHtml(state.editionKey)}</body></html>`;
    const url = URL.createObjectURL(new Blob([doc], { type: "text/html" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `walletbrief-${info.year}-week-${String(info.week).padStart(2, "0")}.html`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showMessage("Het HTML-bestand is gedownload.");
  }

  // --- Navigatie -------------------------------------------------------------------

  function selectEdition(key) {
    if (!key || !state.byWeek.has(key)) return;
    state.editionKey = key;
    try { history.replaceState(null, "", `#editie-${key}`); } catch (e) { /* voorbeeldweergave */ }
    renderEdition();
    $("#editie").scrollIntoView({ block: "start" });
  }

  function showTab(tab) {
    for (const view of document.querySelectorAll(".view")) view.hidden = view.id !== `view-${tab}`;
    for (const a of document.querySelectorAll(".tabs a")) {
      if (a.dataset.tab === tab) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    }
    if (tab === "archief") renderArchive();
  }

  function route() {
    const hash = decodeURIComponent(location.hash.replace(/^#/, ""));
    if (hash.startsWith("editie-") && state.byWeek.has(hash.slice(7))) {
      state.editionKey = hash.slice(7);
      renderEdition();
      showTab("nieuwsbrief");
    } else if (["archief", "dossiers", "bronnen"].includes(hash)) {
      showTab(hash);
    } else if (!hash.startsWith("item-")) {
      showTab("nieuwsbrief");
    }
  }

  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-scroll]");
    if (!target) return;
    const el = document.getElementById(target.dataset.scroll);
    if (!el) return;
    event.preventDefault();
    el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    el.classList.remove("highlight");
    void el.offsetWidth; // animatie opnieuw starten
    el.classList.add("highlight");
    el.setAttribute("tabindex", "-1");
    el.focus({ preventScroll: true });
  });

  // --- Laden ------------------------------------------------------------------------

  async function fetchJson(path) {
    const response = await fetch(path, { cache: "no-cache" });
    if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
    return response.json();
  }

  async function load() {
    let data = window.NIEUWSBRIEF_DATA;
    try {
      if (!data) {
        const [items, config] = await Promise.all([fetchJson("data/items.json"), fetchJson("data/config.json")]);
        data = { items: items.items, generated: items.generated, config };
      }
    } catch (e) {
      $("#laden").textContent = "Er zijn nog geen gegevens. Start in GitHub de workflow 'Nieuwsbrief bijwerken' (Actions > Run workflow) en laad deze pagina daarna opnieuw.";
      return;
    }
    state.items = (data.items || []).filter((i) => i.date);
    state.config = data.config;
    state.generated = data.generated;
    for (const item of state.items) {
      if (item.baseline) continue; // nulmeting zonder datum: wel in het archief, niet in een editie
      if (!state.byWeek.has(weekKey(item.date))) state.byWeek.set(weekKey(item.date), []);
      state.byWeek.get(weekKey(item.date)).push(item);
    }
    state.editions = [...state.byWeek.keys()].sort().reverse();
    state.currentWeek = state.generated ? weekKey(state.generated.slice(0, 10)) : null;
    state.editionKey = state.editions[0] || null;

    $("#laden").hidden = true;
    $("#bijgewerkt").textContent = state.generated
      ? `Laatst bijgewerkt: ${fmtStamp.format(new Date(state.generated))}. ${state.items.length} berichten in het archief.` : "";
    if (state.editionKey) renderEdition();
    else $("#editie").innerHTML = '<p class="empty">Nog geen berichten gevonden. De eerstvolgende run vult de nieuwsbrief.</p>';
    setupArchive();
    renderDossiers();
    renderSources();
    route();
    window.addEventListener("hashchange", route);
  }

  load();
})();
