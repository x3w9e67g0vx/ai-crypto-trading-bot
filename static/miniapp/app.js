(() => {
    "use strict";

    const tg = window.Telegram && window.Telegram.WebApp;
    const initData = (tg && tg.initData) || "";
    const DISCLAIMER_KEY = "vx_disclaimer_v1";
    const CANDLE_SEC = 300;

    const state = {
        strings: {},
        lang: "ru",
        me: null,
        season: "week",
        symbol: "BTC/USDT",
        tab: "trade",
        quotes: null,
        timers: [],
        chart: null,
        series: null,
        lastBar: null,
        // Lesson to open on the next visit to the lessons tab (after a micro lesson).
        lesson: null,
    };

    const $ = (selector, root = document) => root.querySelector(selector);
    const screen = $("#screen");

    // ---------- text ----------

    function t(key, vars = {}) {
        const table = state.strings[state.lang] || {};
        const template = table[key] ?? (state.strings.en || {})[key] ?? key;
        return template.replace(/\{(\w+)\}/g, (_, name) => (name in vars ? vars[name] : `{${name}}`));
    }

    function esc(value) {
        return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
    }

    function money(value) {
        return Number(value).toLocaleString(state.lang, { maximumFractionDigits: 2 });
    }

    function price(value) {
        if (value == null) return "—";
        // Cents for big prices so bid and ask stay distinguishable; small coins keep 6 significant digits.
        const options = Math.abs(value) >= 1000 ? { minimumFractionDigits: 2, maximumFractionDigits: 2 } : { maximumSignificantDigits: 6 };
        return Number(value).toLocaleString(state.lang, options);
    }

    function pct(value) {
        const sign = value > 0 ? "+" : "";
        return `${sign}${Number(value).toLocaleString(state.lang, { maximumFractionDigits: 2 })}%`;
    }

    function trend(value) {
        return value > 0 ? "up" : value < 0 ? "down" : "";
    }

    function duration(ms) {
        const minutes = Math.max(0, Math.floor(ms / 60000));
        const d = Math.floor(minutes / 1440);
        const h = Math.floor((minutes % 1440) / 60);
        const m = minutes % 60;
        if (d) return `${d} ${t("unit.d")} ${h} ${t("unit.h")}`;
        if (h) return `${h} ${t("unit.h")} ${m} ${t("unit.m")}`;
        return `${m} ${t("unit.m")}`;
    }

    function clock(ms) {
        return new Date(ms).toLocaleTimeString(state.lang, { hour: "2-digit", minute: "2-digit" });
    }

    function applyStatic() {
        document.documentElement.lang = state.lang;
        document.querySelectorAll("[data-i18n]").forEach((el) => {
            el.textContent = t(el.dataset.i18n);
        });
    }

    // ---------- feedback ----------

    let toastTimer = null;
    function toast(message) {
        const el = $("#toast");
        el.textContent = message;
        el.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => (el.hidden = true), 2800);
    }

    function haptic(kind) {
        if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred(kind);
    }

    function errorText(error) {
        const key = `errors.${error.code}`;
        const table = state.strings[state.lang] || {};
        return key in table ? t(key) : t("errors.game_error");
    }

    // ---------- api ----------

    class ApiError extends Error {
        constructor(code, status) {
            super(code);
            this.code = code;
            this.status = status;
        }
    }

    async function api(path, { method = "GET", body } = {}) {
        let response;
        try {
            response = await fetch(path, {
                method,
                headers: { Authorization: `tma ${initData}`, ...(body ? { "Content-Type": "application/json" } : {}) },
                body: body ? JSON.stringify(body) : undefined,
            });
        } catch {
            throw new ApiError("network", 0);
        }
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const detail = data && data.detail;
            const code = detail && typeof detail === "object" && detail.code ? detail.code : "game_error";
            throw new ApiError(code, response.status);
        }
        return data;
    }

    // ---------- modal ----------

    function modal(html, bind) {
        const dialog = $("#modal");
        dialog.innerHTML = html;
        return new Promise((resolve) => {
            bind(dialog, (value) => {
                dialog.close();
                resolve(value);
            });
            dialog.showModal();
        });
    }

    function disclaimerModal() {
        if (localStorage.getItem(DISCLAIMER_KEY)) return Promise.resolve();
        return modal(
            `<h2>${esc(t("disclaimer.title"))}</h2>
             <p>${esc(t("disclaimer"))}</p>
             <button class="primary" id="accept">${esc(t("disclaimer.accept"))}</button>`,
            (dialog, done) => {
                dialog.addEventListener("cancel", (event) => event.preventDefault());
                $("#accept", dialog).onclick = () => {
                    localStorage.setItem(DISCLAIMER_KEY, "1");
                    done();
                };
            },
        );
    }

    function tipModal(tip) {
        return modal(
            `<h2>${esc(t("tip.title"))}</h2>
             <p>${esc(t(`tip.${tip.code}`))}</p>
             <div class="tip-actions">
               <button class="primary" id="tip-open">${esc(t("tip.open"))}</button>
               <button id="tip-ok">${esc(t("tip.ok"))}</button>
             </div>`,
            (dialog, done) => {
                dialog.addEventListener("cancel", () => done(false), { once: true });
                $("#tip-open", dialog).onclick = () => done(true);
                $("#tip-ok", dialog).onclick = () => done(false);
            },
        );
    }

    function nicknameModal({ required }) {
        return modal(
            `<h2>${esc(t("nickname.title"))}</h2>
             <form method="dialog" id="nick-form">
               <label class="field">
                 <input id="nick" maxlength="16" autocomplete="off" value="${esc(state.me.player.nickname)}" />
                 <span class="hint">${esc(t("nickname.hint"))}</span>
               </label>
               <p class="form-error" id="nick-error"></p>
               <button class="primary" type="submit">${esc(t("nickname.save"))}</button>
             </form>`,
            (dialog, done) => {
                if (required) dialog.addEventListener("cancel", (event) => event.preventDefault());
                $("#nick-form", dialog).onsubmit = async (event) => {
                    event.preventDefault();
                    try {
                        state.me = await api("/game/me", { method: "PATCH", body: { nickname: $("#nick", dialog).value } });
                        done(true);
                    } catch (error) {
                        $("#nick-error", dialog).textContent = errorText(error);
                    }
                };
            },
        );
    }

    // ---------- navigation ----------

    function stopTimers() {
        state.timers.forEach(clearInterval);
        state.timers = [];
        if (state.chart) {
            state.chart.remove();
            state.chart = null;
            state.series = null;
            state.lastBar = null;
        }
    }

    function every(ms, fn) {
        state.timers.push(setInterval(fn, ms));
    }

    async function go(tab) {
        stopTimers();
        state.tab = tab;
        document.querySelectorAll("#tabs button").forEach((button) => {
            if (button.dataset.tab === tab) button.setAttribute("aria-current", "page");
            else button.removeAttribute("aria-current");
        });
        try {
            await screens[tab]();
        } catch (error) {
            screen.innerHTML = `<p class="empty">${esc(errorText(error))}</p>`;
        }
    }

    function seasonSwitch() {
        return `<div class="segmented" role="group">
            ${["sprint", "week"]
                .map((kind) => `<button data-season="${kind}" aria-pressed="${state.season === kind}">${esc(t(`season.${kind}`))}</button>`)
                .join("")}
        </div>`;
    }

    function bindSeasonSwitch() {
        screen.querySelectorAll("[data-season]").forEach((button) => {
            button.onclick = () => {
                state.season = button.dataset.season;
                go(state.tab);
            };
        });
    }

    // ---------- trade ----------

    function portfolio() {
        return state.me.portfolios[state.season];
    }

    async function refreshMe() {
        state.me = await api("/game/me");
    }

    function renderSeasonMeta() {
        const p = portfolio();
        $("#season-meta").innerHTML = `
            <span class="hint">${esc(t("season.ends_in", { time: duration(p.ends_at - Date.now()) }))}</span>
            <span class="hint">${esc(t("trades_today", { n: p.trades_today, limit: p.trades_limit }))}</span>`;
        $("#balance").innerHTML = `
            <span class="hint">${esc(t("balance"))}</span> <span class="num">${money(p.value)}</span>
            <span class="hint">· ${esc(t("cash"))} ${money(p.cash)} USDT</span>`;
    }

    function renderDuel(ai) {
        const mine = portfolio().return_pct;
        const best = ai.reduce((top, row) => (top == null || row.return_pct > top.return_pct ? row : top), null);
        const theirs = best ? best.return_pct : 0;
        // Half the bar each at a tie; every percentage point of lead tilts it by 10%.
        const share = Math.max(4, Math.min(96, 50 + (mine - theirs) * 10));
        $("#duel").innerHTML = `
            <div class="duel-scores">
              <span class="num ${trend(mine)}">${pct(mine)}</span>
              <span class="num ai-score">${best ? pct(theirs) : "—"}</span>
            </div>
            <div class="duel-bar"><span style="width:${share}%"></span></div>
            <div class="duel-labels hint">
              <span>${esc(t("duel.you"))}</span>
              <span>${esc(best ? t("duel.best_ai", { name: best.nickname }) : t("duel.no_ai"))}</span>
            </div>`;
    }

    function currentQuote() {
        return state.quotes && state.quotes.quotes.find((quote) => quote.symbol === state.symbol);
    }

    function renderQuote() {
        const quote = currentQuote();
        const down = state.quotes.exchange_down || !quote || !quote.fresh;
        const banner = $("#banner");
        banner.hidden = !down;
        banner.textContent = t("exchange_down");
        const mid = quote && quote.bid != null ? (quote.bid + quote.ask) / 2 : null;
        $("#quote").innerHTML = `
            <span class="num">${price(mid)}</span>
            <span class="hint">${esc(t("prices_source"))}</span>`;
        const long = $("#buy-long");
        const short = $("#sell-short");
        long.textContent = t("order.long", { price: price(quote && quote.ask) });
        short.textContent = t("order.short", { price: price(quote && quote.bid) });
        long.disabled = short.disabled = down;
        if (mid != null && state.series) {
            const bucket = Math.floor(quote.ts / 1000 / CANDLE_SEC) * CANDLE_SEC;
            const last = state.lastBar;
            const bar =
                last && last.time === bucket
                    ? { ...last, high: Math.max(last.high, mid), low: Math.min(last.low, mid), close: mid }
                    : last && last.time > bucket
                      ? null
                      : { time: bucket, open: last ? last.close : mid, high: mid, low: mid, close: mid };
            if (bar) {
                state.series.update(bar);
                state.lastBar = bar;
            }
        }
    }

    async function refreshQuotes() {
        state.quotes = await api("/game/quotes");
        renderQuote();
    }

    function renderPositions(rows) {
        const list = $("#positions");
        if (!rows.length) {
            list.innerHTML = `<li class="empty">${esc(t("positions.empty"))}</li>`;
            return;
        }
        list.innerHTML = rows
            .map(
                (row) => `<li>
                  <div class="grow">
                    <div><strong>${esc(row.symbol)}</strong>
                      <span class="side-tag ${row.side === "long" ? "up" : "down"}">${esc(t(`side.${row.side}`))}</span></div>
                    <div class="hint">${esc(t("positions.entry", { price: price(row.entry_price) }))} · ${money(row.reserved)} USDT</div>
                  </div>
                  <span class="num ${trend(row.unrealized_pnl)}">${row.unrealized_pnl == null ? "—" : money(row.unrealized_pnl)}</span>
                  <button class="small-btn" data-close="${row.id}">${esc(t("positions.close"))}</button>
                </li>`,
            )
            .join("");
        list.querySelectorAll("[data-close]").forEach((button) => {
            button.onclick = async () => {
                button.disabled = true;
                try {
                    await api(`/game/positions/${button.dataset.close}/close`, { method: "POST" });
                    haptic("success");
                    toast(t("positions.closed"));
                    await refreshTrade();
                } catch (error) {
                    haptic("error");
                    toast(errorText(error));
                    button.disabled = false;
                }
            };
        });
    }

    const HISTORY_ROWS = 10;

    function renderHistory(rows) {
        const list = $("#history");
        if (!rows.length) {
            list.innerHTML = `<li class="empty">${esc(t("positions.history_empty"))}</li>`;
            return;
        }
        list.innerHTML = rows
            .slice(0, HISTORY_ROWS)
            .map(
                (row) => `<li>
                  <div class="grow">
                    <div><strong>${esc(row.symbol)}</strong>
                      <span class="side-tag ${row.side === "long" ? "up" : "down"}">${esc(t(`side.${row.side}`))}</span></div>
                    <div class="hint">${esc(t(`reason.${row.close_reason}`))} · ${clock(row.closed_at)}</div>
                  </div>
                  <span class="num ${trend(row.pnl)}">${money(row.pnl)}</span>
                  <button class="small-btn" data-review="${row.id}">${esc(t("positions.review"))}</button>
                </li>`,
            )
            .join("");
        list.querySelectorAll("[data-review]").forEach((button) => {
            button.onclick = () => reviewModal(button.dataset.review);
        });
    }

    function indicatorsLine(snapshot) {
        if (!snapshot) return t("review.no_data");
        const rsi = snapshot.rsi == null ? "—" : Math.round(snapshot.rsi);
        return t("review.indicators", { rsi, trend: t(`review.trend.${snapshot.trend}`) });
    }

    async function reviewModal(positionId) {
        let review;
        try {
            review = await api(`/game/positions/${positionId}/review`);
        } catch (error) {
            toast(errorText(error));
            return;
        }
        const r = review.result;
        const ai = review.ai.length
            ? review.ai
                  .map((row) => `<li><div class="grow">${esc(row.nickname)} — ${esc(t(`ai.view.${row.view}`))}</div>
                      <span class="hint">${Math.round(row.probability_up * 100)}%</span></li>`)
                  .join("")
            : `<li class="hint">${esc(t("review.ai_none"))}</li>`;
        const notes = review.notes.map((code) => `<li>${esc(t(`note.${code}`))}</li>`).join("");
        const result = t("review.result", {
            pnl: money(r.pnl),
            pct: pct(r.pnl_pct),
            time: duration(r.duration_ms),
            reason: t(`reason.${r.close_reason}`),
        });
        await modal(
            `<h2>${esc(t("review.title", { symbol: review.symbol, side: t(`side.${review.side}`) }))}</h2>
             <p class="num ${trend(r.pnl)}">${esc(result)}</p>
             <p class="hint">${esc(t("review.prices", { entry: price(r.entry_price), exit: price(r.exit_price) }))}</p>
             <ul class="list">
               <li><div class="grow hint">${esc(t("review.entry"))}</div><span>${esc(indicatorsLine(review.entry))}</span></li>
               <li><div class="grow hint">${esc(t("review.exit"))}</div><span>${esc(indicatorsLine(review.exit))}</span></li>
             </ul>
             <h3>${esc(t("review.ai"))}</h3>
             <ul class="list">${ai}</ul>
             ${notes ? `<h3>${esc(t("review.notes"))}</h3><ul class="notes">${notes}</ul>` : ""}
             <button class="primary" id="review-close">${esc(t("review.close"))}</button>`,
            (dialog, done) => {
                dialog.addEventListener("cancel", () => done(), { once: true });
                $("#review-close", dialog).onclick = () => done();
            },
        );
    }

    async function refreshTrade() {
        const [rows, closed] = await Promise.all([
            api(`/game/positions?season=${state.season}`),
            api(`/game/positions?season=${state.season}&status=closed`),
            refreshMe(),
        ]);
        renderPositions(rows);
        renderHistory(closed);
        renderSeasonMeta();
    }

    async function refreshDuel() {
        renderDuel(await api(`/game/ai?season=${state.season}`));
    }

    function chartColors() {
        const css = getComputedStyle(document.documentElement);
        return { text: css.getPropertyValue("--hint").trim(), line: css.getPropertyValue("--line").trim() };
    }

    async function loadChart() {
        if (!window.LightweightCharts) return;
        const colors = chartColors();
        const el = $("#chart");
        state.chart = LightweightCharts.createChart(el, {
            height: el.clientHeight,
            layout: { background: { color: "transparent" }, textColor: colors.text },
            grid: { vertLines: { visible: false }, horzLines: { color: colors.line } },
            rightPriceScale: { borderVisible: false },
            timeScale: { borderVisible: false, timeVisible: true },
            handleScale: false,
        });
        state.series = state.chart.addCandlestickSeries({
            upColor: "#1f9d6b",
            downColor: "#d9475b",
            borderVisible: false,
            wickUpColor: "#1f9d6b",
            wickDownColor: "#d9475b",
        });
        const candles = await api(`/game/candles?symbol=${encodeURIComponent(state.symbol)}`);
        state.series.setData(candles);
        state.lastBar = candles.length ? candles[candles.length - 1] : null;
        state.chart.timeScale().fitContent();
    }

    function readStop(id) {
        const raw = $(id).value.trim().replace(",", ".");
        return raw ? Number(raw) : null;
    }

    async function placeOrder(side) {
        const amount = Number($("#amount").value.replace(",", "."));
        try {
            const position = await api("/game/orders", {
                method: "POST",
                body: {
                    season: state.season,
                    symbol: state.symbol,
                    side,
                    amount_usdt: amount,
                    stop_loss: readStop("#stop-loss"),
                    take_profit: readStop("#take-profit"),
                },
            });
            haptic("success");
            toast(t("order.placed"));
            $("#stop-loss").value = $("#take-profit").value = "";
            await refreshTrade();
            for (const tip of position.tips || []) {
                if (await tipModal(tip)) {
                    openLesson(tip.lesson_id);
                    break;
                }
            }
        } catch (error) {
            haptic("error");
            toast(errorText(error));
        }
    }

    async function tradeScreen() {
        const symbols = (state.quotes && state.quotes.symbols) || ["BTC/USDT", "ETH/USDT", "SOL/USDT"];
        screen.innerHTML = `
            ${seasonSwitch()}
            <div class="season-meta" id="season-meta"></div>
            <section class="duel" id="duel" aria-live="polite"></section>
            <p id="balance"></p>
            <div class="pairs" role="group">
              ${symbols.map((symbol) => `<button data-symbol="${esc(symbol)}" aria-pressed="${symbol === state.symbol}">${esc(symbol.replace("/USDT", ""))}</button>`).join("")}
            </div>
            <div class="quote-row" id="quote"></div>
            <div id="chart"></div>
            <section class="ticket">
              <label class="field">
                <span class="hint">${esc(t("order.amount"))}</span>
                <input id="amount" inputmode="decimal" value="1000" />
              </label>
              <div class="chips">
                ${[10, 25, 50].map((share) => `<button data-share="${share}">${share}%</button>`).join("")}
              </div>
              <p class="hint">${esc(t("order.max_hint"))}</p>
              <details class="stops">
                <summary>${esc(t("order.stops"))} (${esc(t("order.optional"))})</summary>
                <div class="stops-grid">
                  <label class="field"><span class="hint">${esc(t("order.stop_loss"))}</span><input id="stop-loss" inputmode="decimal" /></label>
                  <label class="field"><span class="hint">${esc(t("order.take_profit"))}</span><input id="take-profit" inputmode="decimal" /></label>
                </div>
              </details>
              <div class="sides">
                <button class="long" id="buy-long"></button>
                <button class="short" id="sell-short"></button>
              </div>
            </section>
            <h2>${esc(t("positions.open"))}</h2>
            <ul class="list" id="positions"></ul>
            <h2>${esc(t("positions.history"))}</h2>
            <ul class="list" id="history"></ul>`;

        bindSeasonSwitch();
        screen.querySelectorAll("[data-symbol]").forEach((button) => {
            button.onclick = () => {
                state.symbol = button.dataset.symbol;
                go("trade");
            };
        });
        screen.querySelectorAll("[data-share]").forEach((button) => {
            button.onclick = () => {
                const amount = Math.floor((portfolio().value * Number(button.dataset.share)) / 100);
                $("#amount").value = String(amount);
            };
        });
        $("#buy-long").onclick = () => placeOrder("long");
        $("#sell-short").onclick = () => placeOrder("short");

        renderSeasonMeta();
        await Promise.all([refreshQuotes(), refreshTrade(), refreshDuel(), loadChart()]);
        renderQuote();
        every(2000, () => refreshQuotes().catch(() => {}));
        every(5000, () => refreshTrade().catch(() => {}));
        every(30000, () => refreshDuel().catch(() => {}));
        every(30000, () => renderSeasonMeta());
    }

    // ---------- ranking ----------

    async function rankScreen() {
        const board = await api(`/game/leaderboard?season=${state.season}`);
        const title = board.scope === "group" ? t("rank.group", { tier: t(`league.${board.tier}`) }) : t("rank.global");
        const rows = board.rows.length
            ? board.rows
                  .map((row) => {
                      const note = row.is_ai ? t("rank.ai_ghost") : row.qualified ? t("rank.trades", { n: row.trades }) : t("rank.unranked");
                      return `<li class="${row.is_ai ? "ai-row" : ""} ${row.is_me ? "me" : ""}">
                        <span class="rank-cell num">${row.rank ?? "–"}</span>
                        <div class="grow"><div class="nick">${esc(row.nickname)}</div><div class="hint">${esc(note)}</div></div>
                        <span class="num ${trend(row.return_pct)}">${pct(row.return_pct)}</span>
                      </li>`;
                  })
                  .join("")
            : `<li class="empty">${esc(t("rank.empty"))}</li>`;
        screen.innerHTML = `${seasonSwitch()}<h2>${esc(title)}</h2><ul class="list">${rows}</ul>`;
        bindSeasonSwitch();
    }

    // ---------- AI ----------

    async function aiScreen() {
        const personas = await api(`/game/ai?season=${state.season}`);
        const delayed = personas.some((row) => row.delayed);
        const blocks = personas
            .map((row) => {
                const positions = row.positions.length
                    ? row.positions
                          .map(
                              (p) => `<li><div class="grow"><strong>${esc(p.symbol)}</strong>
                                <span class="side-tag ${p.side === "long" ? "up" : "down"}">${esc(t(`side.${p.side}`))}</span></div>
                                <span class="hint">${esc(t("positions.entry", { price: price(p.entry_price) }))}</span></li>`,
                          )
                          .join("")
                    : `<li class="hint">${esc(t("ai.no_positions"))}</li>`;
                const decisions = row.decisions.length
                    ? row.decisions
                          .slice(0, 6)
                          .map(
                              (d) => `<li><div class="grow">${esc(d.symbol)} — ${esc(t(`ai.view.${d.view}`))}</div>
                                <span class="hint">${Math.round(d.probability_up * 100)}% · ${clock(d.created_at)}</span></li>`,
                          )
                          .join("")
                    : `<li class="hint">${esc(t("ai.no_decisions"))}</li>`;
                return `<section class="persona">
                    <h3><span>${esc(row.nickname)}</span><span class="num ${trend(row.return_pct)}">${pct(row.return_pct)}</span></h3>
                    <p class="hint">${esc(t(`ai.persona.${row.key}`))}</p>
                    <h2>${esc(t("ai.positions"))}</h2><ul class="list">${positions}</ul>
                    <h2>${esc(t("ai.decisions"))}</h2><ul class="list">${decisions}</ul>
                  </section>`;
            })
            .join("");
        screen.innerHTML = `${seasonSwitch()}
            ${delayed ? `<p class="hint">${esc(t("ai.delayed"))}</p>` : ""}
            ${blocks || `<p class="empty">${esc(t("duel.no_ai"))}</p>`}`;
        bindSeasonSwitch();
    }

    // ---------- lessons ----------

    // Mirrors XP_PER_TRADE in app/game/config.py.
    const XP_PER_TRADE = 10;

    function levelCard(player) {
        const top = player.next_level_xp == null;
        const progress = top
            ? t("learn.max", { xp: player.xp })
            : t("learn.progress", { xp: player.xp, next: player.next_level_xp });
        const share = top ? 100 : Math.round(((player.xp - player.level_xp) / (player.next_level_xp - player.level_xp)) * 100);
        const unlocks = player.next_unlocks.length
            ? `<p class="hint">${esc(t("learn.next_unlocks", { pairs: player.next_unlocks.map((s) => s.replace("/USDT", "")).join(", ") }))}</p>`
            : "";
        return `<section class="level-card">
            <h3><span>${esc(t("learn.level", { level: player.level }))}</span><span class="hint">${esc(progress)}</span></h3>
            <div class="level-bar"><span style="width:${share}%"></span></div>
            ${unlocks}
        </section>`;
    }

    // Lesson text is escaped first; only **bold** becomes markup.
    function inline(text) {
        return esc(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    }

    function lessonBody(blocks) {
        let html = "";
        let list = false;
        for (const block of blocks) {
            if (block.type === "li" && !list) html += "<ul>";
            if (block.type !== "li" && list) html += "</ul>";
            list = block.type === "li";
            const tag = { h: "h3", p: "p", li: "li" }[block.type];
            html += `<${tag}>${inline(block.text)}</${tag}>`;
        }
        return list ? `${html}</ul>` : html;
    }

    function openLesson(lessonId) {
        state.lesson = lessonId;
        go("learn");
    }

    async function lessonScreen(lessonId) {
        const lesson = await api(`/game/lessons/${encodeURIComponent(lessonId)}`);
        screen.innerHTML = `
            <button class="small-btn" id="lessons-back">${esc(t("learn.back"))}</button>
            <article class="lesson">
              <h2>${esc(lesson.title)}${lesson.done ? ` <span class="side-tag up">${esc(t("learn.done"))}</span>` : ""}</h2>
              ${lessonBody(lesson.blocks)}
            </article>
            <section class="quiz">
              <h3>${esc(t("learn.quiz"))}</h3>
              <p>${esc(lesson.question)}</p>
              <div class="quiz-options">
                ${lesson.options.map((option, index) => `<button data-answer="${index}">${esc(option)}</button>`).join("")}
              </div>
              <p class="form-error" id="quiz-error"></p>
            </section>`;
        $("#lessons-back").onclick = () => go("learn");
        screen.querySelectorAll("[data-answer]").forEach((button) => {
            button.onclick = async () => {
                try {
                    const result = await api(`/game/lessons/${encodeURIComponent(lessonId)}/complete`, {
                        method: "POST",
                        body: { answer: Number(button.dataset.answer) },
                    });
                    haptic("success");
                    toast(result.xp_awarded ? t("learn.passed", { xp: result.xp_awarded }) : t("learn.passed_again"));
                    go("learn");
                } catch (error) {
                    haptic("error");
                    button.disabled = true;
                    $("#quiz-error").textContent = errorText(error);
                }
            };
        });
        window.scrollTo(0, 0);
    }

    async function learnScreen() {
        if (state.lesson) {
            const lessonId = state.lesson;
            state.lesson = null;
            await lessonScreen(lessonId);
            return;
        }
        const [lessons] = await Promise.all([api("/game/lessons"), refreshMe()]);
        const rows = lessons
            .map(
                (lesson) => `<li>
                  <div class="grow"><strong>${esc(lesson.title)}</strong></div>
                  <span class="${lesson.done ? "side-tag up" : "hint"}">${esc(lesson.done ? t("learn.done") : t("learn.reward", { xp: lesson.xp }))}</span>
                  <button class="small-btn" data-lesson="${esc(lesson.id)}">›</button>
                </li>`,
            )
            .join("");
        screen.innerHTML = `${levelCard(state.me.player)}
            <p class="hint">${esc(t("learn.how", { xp: lessons.length ? lessons[0].xp : 0, trade_xp: XP_PER_TRADE }))}</p>
            <ul class="list">${rows}</ul>`;
        screen.querySelectorAll("[data-lesson]").forEach((button) => {
            button.onclick = () => lessonScreen(button.dataset.lesson);
        });
    }

    // ---------- share ----------

    function canShareStory() {
        return Boolean(tg && tg.shareToStory && tg.isVersionAtLeast && tg.isVersionAtLeast("7.8"));
    }

    function shareModal(data) {
        return modal(
            `<h2>${esc(t("share.title"))}</h2>
             <img class="share-card" src="${esc(data.image_url)}" alt="">
             <p>${esc(data.text)}</p>
             <div class="tip-actions">
               ${data.link ? `<button class="primary" id="share-send">${esc(t("share.send"))}</button>` : ""}
               ${canShareStory() ? `<button id="share-story">${esc(t("share.story"))}</button>` : ""}
               <button id="share-close">${esc(t("share.close"))}</button>
             </div>`,
            (dialog, done) => {
                dialog.addEventListener("cancel", () => done(), { once: true });
                const send = $("#share-send", dialog);
                if (send) {
                    send.onclick = () => {
                        const url = `https://t.me/share/url?url=${encodeURIComponent(data.link)}&text=${encodeURIComponent(data.text)}`;
                        tg.openTelegramLink(url);
                        done();
                    };
                }
                const story = $("#share-story", dialog);
                if (story) {
                    story.onclick = () => {
                        // Telegram downloads the card itself, so it needs an absolute URL.
                        const media = new URL(data.image_url, location.origin).href;
                        tg.shareToStory(media, { text: data.link ? `${data.text} ${data.link}` : data.text });
                        done();
                    };
                }
                $("#share-close", dialog).onclick = () => done();
            },
        );
    }

    async function share() {
        try {
            await shareModal(await api("/game/share", { method: "POST", body: { season: state.season } }));
        } catch (error) {
            toast(errorText(error));
        }
    }

    // ---------- profile ----------

    async function profileScreen() {
        await refreshMe();
        const player = state.me.player;
        const badges = player.badges.length
            ? player.badges.map((badge) => `<li>${esc(t(`badge.${badge.code}`))}</li>`).join("")
            : `<li class="hint">${esc(t("profile.no_badges"))}</li>`;
        screen.innerHTML = `
            <ul class="list">
              <li><div class="grow"><div class="hint">${esc(t("profile.nickname"))}</div><strong>${esc(player.nickname)}</strong></div>
                <button class="small-btn" id="change-nick">${esc(t("profile.change"))}</button></li>
              <li><div class="grow hint">${esc(t("profile.language"))}</div>
                <select id="language">
                  <option value="ru" ${player.language === "ru" ? "selected" : ""}>Русский</option>
                  <option value="en" ${player.language === "en" ? "selected" : ""}>English</option>
                </select></li>
              <li><div class="grow hint">${esc(t("profile.league"))}</div><strong>${esc(t(`league.${player.league_tier}`))}</strong></li>
              <li><div class="grow hint">${esc(t("profile.xp"))}</div><span class="num">${player.xp}</span></li>
            </ul>
            ${levelCard(player)}
            <h2>${esc(t("share.title"))}</h2>
            ${seasonSwitch()}
            <p class="hint">${esc(t("share.hint"))}</p>
            <button class="primary" id="share">${esc(t("share.button"))}</button>
            <h2>${esc(t("profile.badges"))}</h2>
            <ul class="list">${badges}</ul>`;
        bindSeasonSwitch();
        $("#share").onclick = share;
        $("#change-nick").onclick = async () => {
            if (await nicknameModal({ required: false })) {
                toast(t("saved"));
                go("profile");
            }
        };
        $("#language").onchange = async (event) => {
            try {
                state.me = await api("/game/me", { method: "PATCH", body: { language: event.target.value } });
                state.lang = state.me.player.language;
                applyStatic();
                go("profile");
            } catch (error) {
                toast(errorText(error));
            }
        };
    }

    const screens = { trade: tradeScreen, rank: rankScreen, ai: aiScreen, learn: learnScreen, profile: profileScreen };

    // ---------- boot ----------

    async function boot() {
        state.strings = await fetch("/static/miniapp/i18n.json").then((response) => response.json());
        const tgLang = tg && tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.language_code;
        state.lang = String(tgLang || navigator.language || "ru").toLowerCase().startsWith("ru") ? "ru" : "en";
        applyStatic();

        if (!initData) {
            screen.innerHTML = `<p class="empty">${esc(t("open_in_telegram"))}</p>`;
            return;
        }
        tg.ready();
        tg.expand();

        try {
            state.me = await api("/game/me");
        } catch (error) {
            screen.innerHTML = `<p class="empty">${esc(errorText(error))}</p>`;
            return;
        }
        state.lang = state.me.player.language;
        applyStatic();

        $("#tabs").hidden = false;
        document.querySelectorAll("#tabs button").forEach((button) => {
            button.onclick = () => go(button.dataset.tab);
        });

        await disclaimerModal();
        if (state.me.player.needs_nickname) await nicknameModal({ required: true });
        go(location.hash === "#learn" ? "learn" : "trade");
    }

    boot();
})();
