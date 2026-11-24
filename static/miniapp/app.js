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
        rankBy: "return",
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

    // The friend duel lives only on the trade and ranking screens, and only while it runs.
    const DUEL_TABS = ["trade", "rank"];

    function hasDuel() {
        return Boolean(state.me && state.me.portfolios.duel);
    }

    async function go(tab) {
        stopTimers();
        state.tab = tab;
        if (state.season === "duel" && (!DUEL_TABS.includes(tab) || !hasDuel())) state.season = "sprint";
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
            ${["sprint", "week", ...(hasDuel() && DUEL_TABS.includes(state.tab) ? ["duel"] : [])]
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

    function streakLine() {
        const st = state.me && state.me.streak;
        if (!st || !st.days) return `<p class="hint">${esc(t("streak.start"))}</p>`;
        const left = st.next_milestone ? ` · ${t("streak.next", { n: st.next_milestone - st.days })}` : "";
        const todo = st.today_done ? "" : ` · ${t("streak.todo")}`;
        return `<p class="streak ${st.today_done ? "" : "at-risk"}">🔥 ${esc(t("streak.days", { n: st.days }))}<span class="hint">${esc(left + todo)}</span></p>`;
    }

    async function refreshMe() {
        state.me = await api("/game/me");
        if (state.me.streak && state.me.streak.xp_awarded) {
            haptic("success");
            toast(t("streak.toast", { n: state.me.streak.days, xp: state.me.streak.xp_awarded }));
        }
        const streakBox = $("#streak");
        if (streakBox) streakBox.innerHTML = streakLine();
        // The duel just ended: back to the sprint screen.
        if (state.season === "duel" && !hasDuel()) setTimeout(() => go(state.tab));
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
        const best = ai.reduce((top, row) => (top == null || row.return_pct > top.return_pct ? row : top), null);
        renderVersus(portfolio().return_pct, best ? best.return_pct : null,
            best ? t("duel.best_ai", { name: best.nickname }) : t("duel.no_ai"));
    }

    function renderVersus(mine, rival, rivalLabel) {
        const theirs = rival ?? 0;
        // Half the bar each at a tie; every percentage point of lead tilts it by 10%.
        const share = Math.max(4, Math.min(96, 50 + (mine - theirs) * 10));
        $("#duel").innerHTML = `
            <div class="duel-scores">
              <span class="num ${trend(mine)}">${pct(mine)}</span>
              <span class="num ai-score">${rival != null ? pct(theirs) : "—"}</span>
            </div>
            <div class="duel-bar"><span style="width:${share}%"></span></div>
            <div class="duel-labels hint">
              <span>${esc(t("duel.you"))}</span>
              <span>${esc(rivalLabel)}</span>
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
             <p class="grade grade-${review.grade}">${esc(t(`grade.${review.grade}`))}</p>
             <p class="hint">${esc(t("review.prices", { entry: price(r.entry_price), exit: price(r.exit_price) }))}</p>
             <ul class="list">
               <li><div class="grow hint">${esc(t("review.entry"))}</div><span>${esc(indicatorsLine(review.entry))}</span></li>
               <li><div class="grow hint">${esc(t("review.exit"))}</div><span>${esc(indicatorsLine(review.exit))}</span></li>
             </ul>
             <h3>${esc(t("review.ai"))}</h3>
             <ul class="list">${ai}</ul>
             ${notes ? `<h3>${esc(t("review.notes"))}</h3><ul class="notes">${notes}</ul>` : ""}
             <div id="llm-box"><button class="small-btn" id="llm-review">${esc(t(state.me.player.is_pro ? "review.llm" : "review.llm_pro"))}</button></div>
             <button class="primary" id="review-close">${esc(t("review.close"))}</button>`,
            (dialog, done) => {
                dialog.addEventListener("cancel", () => done(), { once: true });
                $("#review-close", dialog).onclick = () => done();
                $("#llm-review", dialog).onclick = async (event) => {
                    if (!state.me.player.is_pro) return openShop();
                    event.target.disabled = true;
                    event.target.textContent = t("review.llm_loading");
                    try {
                        const body = await api(`/game/positions/${positionId}/review/llm`, { method: "POST" });
                        $("#llm-box", dialog).innerHTML = `<h3>${esc(t("review.llm_title"))}</h3><p class="llm-text">${esc(body.text)}</p>`;
                    } catch (error) {
                        event.target.disabled = false;
                        event.target.textContent = t("review.llm");
                        toast(errorText(error));
                    }
                };
            },
        );
    }

    function whyStep(why, code) {
        const pctOrDash = (value) => (value == null ? "—" : pct(value));
        const vars = {
            nickname: why.nickname,
            prob: why.probability_up == null ? "—" : Math.round(why.probability_up * 100),
            threshold: Math.round(why.threshold * 100),
            trend: why.trend ? t(`review.trend.${why.trend}`) : t("review.no_data"),
            rsi: why.rsi == null ? "—" : Math.round(why.rsi),
            amount: `${money(why.amount_usdt)} USDT`,
            price: price(why.entry_price),
            stop: price(why.stop_loss),
            stop_pct: pctOrDash(why.stop_pct),
            take: price(why.take_profit),
            take_pct: pctOrDash(why.take_pct),
        };
        return t(code === "signal" ? `why.signal.${why.side}` : `why.${code}`, vars);
    }

    async function whyModal(positionId) {
        let why;
        try {
            why = await api(`/game/ai/positions/${positionId}/why`);
        } catch (error) {
            toast(errorText(error));
            return;
        }
        const steps = why.steps
            .map((step) => `<li><div class="grow">${esc(whyStep(why, step.code))}</div>
                <button class="small-btn" data-lesson="${esc(step.lesson_id)}">${esc(t("why.lesson"))}</button></li>`)
            .join("");
        const lessonId = await modal(
            `<h2>${esc(t("why.title", { nickname: why.nickname, side: t(`side.${why.side}`), symbol: why.symbol }))}</h2>
             <ol class="list">${steps}</ol>
             <button class="primary" id="why-close">${esc(t("review.close"))}</button>`,
            (dialog, done) => {
                dialog.addEventListener("cancel", () => done(), { once: true });
                $("#why-close", dialog).onclick = () => done();
                dialog.querySelectorAll("[data-lesson]").forEach((button) => {
                    button.onclick = () => done(button.dataset.lesson);
                });
            },
        );
        if (lessonId) openLesson(lessonId);
    }

    async function refreshTrade() {
        const [rows, closed, quests] = await Promise.all([
            api(`/game/positions?season=${state.season}`),
            api(`/game/positions?season=${state.season}&status=closed`),
            state.season === "duel" ? null : api(`/game/quests?season=${state.season}`),
            refreshMe(),
        ]);
        renderPositions(rows);
        renderHistory(closed);
        if (quests) renderQuests(quests);
        renderSeasonMeta();
    }

    function renderQuests(body) {
        const box = $("#quests");
        if (!box) return;
        if (body.xp_awarded) {
            haptic("success");
            toast(t("quests.toast", { xp: body.xp_awarded }));
            state.me.player = body.player;
        }
        const rows = body.quests
            .map((q) => {
                const mark = q.done ? "✓" : q.failed ? "✗" : `${q.progress}/${q.target}`;
                const note = q.failed ? `<div class="hint">${esc(t("quests.failed"))}</div>` : "";
                return `<li class="quest ${q.done ? "done" : ""} ${q.failed ? "failed" : ""}">
                    <div class="grow">${esc(t(`quests.${q.code}`))}${note}<div class="hint">${esc(t("learn.reward", { xp: q.xp }))}</div></div>
                    <span class="num">${mark}</span>
                    <button class="small-btn" data-quest-lesson="${q.lesson_id}">${esc(t("puzzle.lesson"))}</button>
                  </li>`;
            })
            .join("");
        box.innerHTML = `<h3><span>${esc(t("quests.title"))}</span></h3><ul class="list">${rows}</ul>`;
        box.querySelectorAll("[data-quest-lesson]").forEach((button) => {
            button.onclick = () => openLesson(button.dataset.questLesson);
        });
    }

    // ---------- guess the AI ----------

    async function refreshGuess(request) {
        const box = $("#guess");
        if (!box) return;
        let body;
        try {
            body = await (request ?? api(`/game/guess?symbol=${encodeURIComponent(state.symbol)}`));
        } catch (error) {
            if (request) {
                toast(errorText(error));
                return refreshGuess();
            }
            box.hidden = true; // pairs without AI have nothing to guess
            return;
        }
        box.hidden = false;
        renderGuess(box, body);
    }

    function renderGuess(box, body) {
        const g = body.guess;
        state.me.player = body.player;
        if (g.xp_awarded) {
            haptic("success");
            toast(t("guess.toast", { xp: g.xp_awarded }));
        }
        const mark = (ok) => (ok === null ? "–" : ok ? "✓" : "✗");
        const recent = g.recent
            .map((r) => `<li><div class="grow">${esc(r.symbol)} ${clock(r.candle_ts)}
                <div class="hint">${esc(t("guess.result", { price: mark(r.price_correct), ai: mark(r.ai_correct) }))}</div></div>
                <span class="num">+${r.xp} XP</span></li>`)
            .join("");
        const choice = (name, options) => `<div class="segmented" role="group">
            ${options.map((value) => `<button data-${name}="${value}" aria-pressed="false">${esc(t(`guess.${name}.${value}`))}</button>`).join("")}
        </div>`;
        const form = g.current
            ? `<p>${esc(t("guess.placed", { price: t(`guess.price.${g.current.price}`), view: t(`guess.view.${g.current.view}`) }))}</p>`
            : `${choice("price", ["up", "down"])}${choice("view", ["bullish", "neutral", "bearish"])}
               <button class="primary" id="guess-send" disabled>${esc(t("guess.send"))}</button>`;
        box.innerHTML = `<h3><span>${esc(t("guess.title"))}</span>
                <span class="hint">${esc(t("guess.today", { xp: g.xp_today, cap: g.daily_cap }))}</span></h3>
            <p class="hint">${esc(t("guess.prompt", { symbol: g.symbol, time: clock(g.candle_ts), xp: g.xp_per_hit }))}</p>
            ${form}
            ${g.pending ? `<p class="hint">${esc(t("guess.pending", { n: g.pending }))}</p>` : ""}
            ${recent ? `<ul class="list">${recent}</ul>` : ""}`;
        if (g.current) return;
        const picked = {};
        box.querySelectorAll("[data-price], [data-view]").forEach((button) => {
            button.onclick = () => {
                const name = "price" in button.dataset ? "price" : "view";
                picked[name] = button.dataset[name];
                box.querySelectorAll(`[data-${name}]`).forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
                $("#guess-send", box).disabled = !(picked.price && picked.view);
            };
        });
        $("#guess-send", box).onclick = () =>
            refreshGuess(api("/game/guess", { method: "POST", body: { symbol: g.symbol, ...picked } }));
    }

    async function refreshDuel() {
        const inDuel = state.season === "duel";
        const [ai, friend] = await Promise.all([inDuel ? null : api(`/game/ai?season=${state.season}`), api("/game/duel")]);
        if (inDuel && friend.state === "active") renderVersus(friend.my_pct, friend.rival_pct, friend.rival);
        else if (ai) renderDuel(ai);
        renderFriendDuel(inDuel ? { state: "hidden" } : friend);
    }

    function sendDuelInvite(body) {
        if (!body.link) return toast(t("errors.game_error"));
        tg.openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(body.link)}&text=${encodeURIComponent(body.text)}`);
    }

    async function duelAction(method) {
        try {
            const body = await api("/game/duel", { method });
            if (method === "POST") sendDuelInvite(body);
            renderFriendDuel(body);
        } catch (error) {
            toast(errorText(error));
        }
    }

    function renderFriendDuel(d) {
        const box = $("#friend-duel");
        if (!box) return;
        box.hidden = d.state === "hidden";
        const score = d.score && d.score[0] + d.score[1] > 0 ? ` · ${t("fduel.score", { score: d.score.join(":") })}` : "";
        const title = `<h3><span>${esc(t("fduel.title"))}</span></h3>`;
        if (d.state === "open") {
            box.innerHTML = `${title}<p>${esc(t("fduel.waiting", { time: duration(d.expires_at - Date.now()) }))}</p>
                <div class="tip-actions"><button class="primary" data-duel="POST">${esc(t("fduel.resend"))}</button>
                <button data-duel="DELETE">${esc(t("fduel.cancel"))}</button></div>`;
        } else if (d.state === "active") {
            box.innerHTML = `${title}<p>${esc(t("fduel.running", { rival: d.rival }))}
                <span class="num ${trend(d.my_pct)}">${pct(d.my_pct)}</span> / <span class="num ${trend(d.rival_pct)}">${pct(d.rival_pct)}</span>
                <span class="hint">· ${esc(t("season.ends_in", { time: duration(d.ends_at - Date.now()) }))}${esc(score)}</span></p>
                <button class="primary" data-duel-open>${esc(t("fduel.open"))}</button>`;
        } else if (d.state === "finished") {
            const xp = d.xp ? ` · +${d.xp} XP` : "";
            box.innerHTML = `${title}<p>${esc(t(`fduel.${d.outcome}`, { rival: d.rival }))}
                <span class="num ${trend(d.my_pct)}">${pct(d.my_pct)}</span> / <span class="num ${trend(d.rival_pct)}">${pct(d.rival_pct)}</span>
                <span class="hint">${esc(score + xp)}</span></p>
                <button class="primary" data-duel="POST">${esc(t("fduel.rematch"))}</button>`;
        } else {
            box.innerHTML = `${title}<p class="hint">${esc(t("fduel.pitch"))}</p>
                <button class="primary" data-duel="POST">${esc(t("fduel.challenge"))}</button>`;
        }
        box.querySelectorAll("[data-duel]").forEach((button) => {
            button.onclick = () => duelAction(button.dataset.duel);
        });
        const open = box.querySelector("[data-duel-open]");
        if (open) {
            open.onclick = async () => {
                await refreshMe();
                state.season = "duel";
                go("trade");
            };
        }
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
            <div id="streak">${streakLine()}</div>
            <section class="duel" id="duel" aria-live="polite"></section>
            <section class="level-card" id="friend-duel" aria-live="polite"></section>
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
            <section class="level-card" id="guess"></section>
            <section class="level-card" id="quests" ${state.season === "duel" ? "hidden" : ""}></section>
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
        await Promise.all([refreshQuotes(), refreshTrade(), refreshDuel(), loadChart(), refreshGuess()]);
        renderQuote();
        every(2000, () => refreshQuotes().catch(() => {}));
        every(5000, () => refreshTrade().catch(() => {}));
        every(30000, () => refreshDuel().catch(() => {}));
        every(30000, () => refreshGuess());
        every(30000, () => renderSeasonMeta());
    }

    // ---------- ranking ----------

    async function rankScreen() {
        const board = await api(`/game/leaderboard?season=${state.season}`);
        const title = board.scope === "group" ? t("rank.group", { tier: t(`league.${board.tier}`) }) : t("rank.global");
        const byQuality = state.rankBy === "quality";
        if (byQuality) {
            // Same rules as the server ranking: qualified humans only, AI ghosts listed unranked.
            board.rows.sort((a, b) => (a.qualified ? 0 : 1) - (b.qualified ? 0 : 1) || b.quality - a.quality);
            let rank = 0;
            board.rows.forEach((row) => (row.rank = row.qualified && !row.is_ai ? ++rank : null));
        }
        const rows = board.rows.length
            ? board.rows
                  .map((row) => {
                      let note = row.is_ai ? t("rank.ai_ghost") : row.qualified ? t("rank.trades", { n: row.trades }) : t("rank.unranked");
                      if (byQuality) {
                          const stops = row.stop_share === null ? "–" : `${Math.round(row.stop_share * 100)}%`;
                          note = t("rank.quality_note", { dd: pct(-row.drawdown_pct), stops });
                      }
                      const score = byQuality ? row.quality : row.return_pct;
                      return `<li class="${row.is_ai ? "ai-row" : ""} ${row.is_me ? "me" : ""} ${row.frame ? `frame-${row.frame}` : ""}">
                        <span class="rank-cell num">${row.rank ?? "–"}</span>
                        <div class="grow"><div class="nick ${row.nick_color ? `nick-${row.nick_color}` : ""}">${esc(row.nickname)}</div><div class="hint">${esc(note)}</div></div>
                        <span class="num ${trend(score)}">${pct(score)}</span>
                      </li>`;
                  })
                  .join("")
            : `<li class="empty">${esc(t("rank.empty"))}</li>`;
        const rankSwitch = `<div class="segmented" role="group">
            ${["return", "quality"]
                .map((by) => `<button data-rank-by="${by}" aria-pressed="${state.rankBy === by}">${esc(t(`rank.by.${by}`))}</button>`)
                .join("")}
        </div>`;
        screen.innerHTML = `${seasonSwitch()}<h2>${esc(title)}</h2>${rankSwitch}
            ${byQuality ? `<p class="hint">${esc(t("rank.quality_hint"))}</p>` : ""}<ul class="list">${rows}</ul>`;
        bindSeasonSwitch();
        screen.querySelectorAll("[data-rank-by]").forEach((button) => {
            button.onclick = () => {
                state.rankBy = button.dataset.rankBy;
                go(state.tab);
            };
        });
    }

    // ---------- AI ----------

    const AI_SKINS = {
        skin_robots: { lstm: "🤖", random_forest: "🦾", logistic_regression: "📟" },
        skin_beasts: { lstm: "🦉", random_forest: "🦊", logistic_regression: "🐹" },
    };

    function aiAvatar(key) {
        const emoji = (AI_SKINS[state.me?.player.cosmetics.ai_skin] || {})[key];
        return emoji ? `${emoji} ` : "";
    }

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
                                <span class="hint">${esc(t("positions.entry", { price: price(p.entry_price) }))}</span>
                                <button class="small-btn" data-why="${p.id}">${esc(t("ai.why"))}</button></li>`,
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
                    <h3><span>${aiAvatar(row.key)}${esc(row.nickname)}</span><span class="num ${trend(row.return_pct)}">${pct(row.return_pct)}</span></h3>
                    <p class="hint">${esc(t(`ai.persona.${row.key}`))}</p>
                    <h2>${esc(t("ai.positions"))}</h2><ul class="list">${positions}</ul>
                    <h2>${esc(t("ai.decisions"))}</h2><ul class="list">${decisions}</ul>
                  </section>`;
            })
            .join("");
        screen.innerHTML = `${seasonSwitch()}
            ${delayed ? `<p class="hint">${esc(t("ai.delayed"))}</p>` : ""}
            ${blocks || `<p class="empty">${esc(t("duel.no_ai"))}</p>`}`;
        screen.querySelectorAll("[data-why]").forEach((button) => {
            button.onclick = () => whyModal(button.dataset.why);
        });
        bindSeasonSwitch();
    }

    // ---------- daily puzzle ----------

    function historyChart(el) {
        if (!window.LightweightCharts || !el) return null;
        const colors = chartColors();
        state.chart = LightweightCharts.createChart(el, {
            height: el.clientHeight,
            layout: { background: { color: "transparent" }, textColor: colors.text },
            grid: { vertLines: { visible: false }, horzLines: { color: colors.line } },
            rightPriceScale: { borderVisible: false },
            // Times are fake on purpose: the window must not be found by date.
            timeScale: { visible: false },
            handleScale: false,
            handleScroll: false,
        });
        return state.chart.addCandlestickSeries({
            upColor: "#1f9d6b",
            downColor: "#d9475b",
            borderVisible: false,
            wickUpColor: "#1f9d6b",
            wickDownColor: "#d9475b",
        });
    }

    function puzzleChart(view) {
        stopTimers();
        const series = historyChart($("#puzzle-chart"));
        if (!series) return;
        const after = view.result ? view.result.after : [];
        series.setData(view.candles.concat(after));
        const cut = view.candles[view.candles.length - 1];
        if (cut) series.setMarkers([{ time: cut.time, position: "aboveBar", shape: "arrowDown", color: "#9b6bff", text: view.result ? "" : "?" }]);
        state.chart.timeScale().fitContent();
    }

    function puzzleResult(result) {
        const choice = (code) => t(`puzzle.${code}`);
        const verdict = result.correct
            ? t("puzzle.right", { answer: choice(result.answer) })
            : t("puzzle.wrong", { choice: choice(result.choice), answer: choice(result.answer) });
        const why = [t(`puzzle.trend_${result.trend || "none"}`)];
        if (result.rsi != null) {
            const zone = result.rsi >= 70 ? "high" : result.rsi <= 30 ? "low" : "mid";
            why.push(t(`puzzle.rsi_${zone}`, { rsi: Math.round(result.rsi) }));
        }
        return `<p><strong class="${result.correct ? "up" : "down"}">${esc(verdict)}</strong></p>
            <p>${esc(t("puzzle.moved", { symbol: result.symbol.replace("/USDT", ""), move: pct(result.move_pct) }))}</p>
            <p class="hint">${esc(why.join(" "))} ${esc(t("puzzle.note"))}</p>
            <button class="small-btn" id="puzzle-lesson">${esc(t("puzzle.lesson"))}</button>`;
    }

    function renderPuzzle(view) {
        const box = $("#puzzle");
        if (!box) return;
        if (!view) {
            box.remove();
            return;
        }
        const body = view.result
            ? puzzleResult(view.result)
            : `<div class="quiz-options puzzle-choices">
                ${["long", "short", "skip"].map((code) => `<button data-choice="${code}">${esc(t(`puzzle.${code}`))}</button>`).join("")}
              </div>
              <p class="form-error" id="puzzle-error"></p>`;
        box.innerHTML = `<h3><span>${esc(t("puzzle.title"))}</span><span class="hint">${esc(t("learn.reward", { xp: view.xp }))}</span></h3>
            <p class="hint">${esc(t("puzzle.ask"))}</p>
            <div id="puzzle-chart"></div>
            ${body}`;
        puzzleChart(view);
        if (view.result) {
            $("#puzzle-lesson").onclick = () => lessonScreen(view.result.lesson_id);
            return;
        }
        box.querySelectorAll("[data-choice]").forEach((button) => {
            button.onclick = async () => {
                box.querySelectorAll("[data-choice]").forEach((b) => (b.disabled = true));
                try {
                    const result = await api("/game/puzzle", { method: "POST", body: { choice: button.dataset.choice } });
                    haptic(result.xp_awarded ? "success" : "error");
                    if (result.xp_awarded) toast(t("puzzle.toast", { xp: result.xp_awarded }));
                    state.me.player = result.player;
                    renderPuzzle(result.puzzle);
                } catch (error) {
                    haptic("error");
                    box.querySelectorAll("[data-choice]").forEach((b) => (b.disabled = false));
                    $("#puzzle-error").textContent = errorText(error);
                }
            };
        });
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
        const [lessons, puzzle] = await Promise.all([api("/game/lessons"), api("/game/puzzle"), refreshMe()]);
        const rows = lessons
            .map(
                (lesson) => `<li>
                  <div class="grow"><strong>${esc(lesson.title)}</strong></div>
                  <span class="${lesson.done ? "side-tag up" : "hint"}">${esc(lesson.done ? t("learn.done") : t("learn.reward", { xp: lesson.xp }))}</span>
                  <button class="small-btn" data-lesson="${esc(lesson.id)}">›</button>
                </li>`,
            )
            .join("");
        screen.innerHTML = `<div id="streak">${streakLine()}</div><section class="level-card" id="puzzle"></section>
            <section class="level-card"><h3><span>${esc(t("replay.title"))}</span><button class="small-btn" id="replay-open">${esc(t("replay.open"))}</button></h3>
              <p class="hint">${esc(t("replay.about"))}</p></section>
            <section class="level-card"><h3><span>${esc(t("scenario.title"))}</span></h3>
              <p class="hint">${esc(t("scenario.about"))}</p>
              <div class="quiz-options puzzle-choices">${SCENARIO_KINDS.map((kind) => `<button data-scenario="${kind}">${esc(t(`scenario.${kind}`))}</button>`).join("")}</div></section>
            ${levelCard(state.me.player)}
            <p class="hint">${esc(t("learn.how", { xp: lessons.length ? lessons[0].xp : 0, trade_xp: XP_PER_TRADE }))}</p>
            <ul class="list">${rows}</ul>`;
        screen.querySelectorAll("[data-lesson]").forEach((button) => {
            button.onclick = () => lessonScreen(button.dataset.lesson);
        });
        $("#replay-open").onclick = () => replayScreen();
        screen.querySelectorAll("[data-scenario]").forEach((button) => {
            button.onclick = () => replayScreen(button.dataset.scenario);
        });
        renderPuzzle(puzzle.puzzle);
    }

    // ---------- replay trainer ----------

    const REPLAY_TICK_MS = 1600;
    const REPLAY_START = 10000;
    const SCENARIO_KINDS = ["crash", "pump_dump", "flat"];

    // kind = a scenario (crash / pump_dump / flat) with a loss limit; none = a random week.
    async function replayScreen(kind) {
        const replay = kind ? (await api(`/game/scenario?kind=${kind}`)).scenario : (await api("/game/replay")).replay;
        if (!replay) {
            toast(t("replay.none"));
            return;
        }
        screen.innerHTML = `<button class="small-btn" id="replay-back">${esc(t("learn.back"))}</button>
            <section class="level-card">
              <h3><span>${esc(kind ? t(`scenario.${kind}`) : t("replay.title"))}</span><span class="hint">${esc(t("learn.reward", { xp: replay.xp }))}</span></h3>
              ${kind ? `<p><strong>${esc(t("scenario.goal", { loss: replay.max_loss }))}</strong></p>` : ""}
              <p class="hint">${esc(t("replay.ask"))}</p>
              <div id="replay-chart"></div>
              <p id="replay-stats"></p>
              <div class="quiz-options puzzle-choices" id="replay-actions">
                ${["long", "short", "close"].map((code) => `<button data-act="${code}">${esc(t(`replay.${code}`))}</button>`).join("")}
              </div>
              <div id="replay-result"></div>
            </section>`;
        $("#replay-back").onclick = () => go("learn");
        stopTimers();
        const candles = replay.candles;
        const series = historyChart($("#replay-chart"));
        if (series) series.setData(candles.slice(0, replay.show));
        let idx = replay.show;
        let cash = REPLAY_START;
        let pos = null;
        let traded = false;
        const floor = kind ? REPLAY_START * (1 - replay.max_loss / 100) : 0;
        const markers = [];
        const last = () => candles[idx - 1];
        const equity = () => (pos ? cash + pos.qty * (pos.side === "long" ? 1 : -1) * (last().close - pos.entry) : cash);
        const stats = () => {
            const side = pos ? t(`replay.${pos.side}`) : t("replay.flat");
            $("#replay-stats").textContent = t("replay.stats", {
                equity: money(equity()),
                change: pct((equity() / REPLAY_START - 1) * 100),
                side,
                left: candles.length - idx,
            });
            $('[data-act="close"]').disabled = !pos;
        };
        const mark = (text, color) => {
            markers.push({ time: last().time, position: "aboveBar", shape: "circle", color, text });
            if (series) series.setMarkers(markers);
        };
        const close = () => {
            if (!pos) return;
            cash = equity();
            pos = null;
            mark("×", "#9b6bff");
        };
        screen.querySelectorAll("[data-act]").forEach((button) => {
            button.onclick = () => {
                const act = button.dataset.act;
                if (act === "close" || (pos && pos.side !== act)) close();
                if (act !== "close" && !pos) {
                    pos = { side: act, entry: last().close, qty: cash / last().close };
                    traded = true;
                    mark(act === "long" ? "L" : "S", act === "long" ? "#1f9d6b" : "#d9475b");
                }
                stats();
            };
        });
        const finish = async () => {
            // Keep the chart on screen: stop only the tick, not stopTimers().
            state.timers.forEach(clearInterval);
            state.timers = [];
            close();
            $("#replay-actions").hidden = true;
            const mine = (cash / REPLAY_START - 1) * 100;
            const hold = (last().close / candles[replay.show - 1].close - 1) * 100;
            const passed = traded && cash >= floor;
            let xp = 0;
            try {
                const result = kind
                    ? await api("/game/scenario/finish", { method: "POST", body: { passed } })
                    : await api("/game/replay/finish", { method: "POST" });
                xp = result.xp_awarded;
                state.me.player = result.player;
            } catch (error) {
                toast(errorText(error));
            }
            if (xp) toast(t("replay.toast", { xp }));
            if (!$("#replay-result")) return; // the player left the screen meanwhile
            haptic(kind && !passed ? "error" : "success");
            const verdict = kind
                ? t(passed ? "scenario.passed" : traded ? "scenario.failed" : "scenario.no_trade", { loss: replay.max_loss })
                : t(mine >= hold ? "replay.beat" : "replay.lost");
            $("#replay-result").innerHTML = `<p><strong>${esc(t("replay.done", { symbol: replay.symbol.replace("/USDT", ""), mine: pct(mine), hold: pct(hold) }))}</strong></p>
                <p class="hint">${esc(verdict)}</p>
                <button class="small-btn" id="replay-again">${esc(t("replay.again"))}</button>`;
            $("#replay-again").onclick = () => replayScreen(kind);
        };
        stats();
        every(REPLAY_TICK_MS, () => {
            if (idx >= candles.length) return finish();
            if (series) series.update(candles[idx]);
            idx += 1;
            stats();
            if (equity() < floor) finish(); // the loss limit ends a scenario early

        });
        window.scrollTo(0, 0);
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

    function openShop() {
        const link = state.me.player.shop_link;
        if (link) tg.openTelegramLink(link);
        else toast(t("errors.shop_unavailable"));
    }

    function proCard(player) {
        const status = player.is_pro
            ? t("pro.active", { date: new Date(player.pro_until).toLocaleDateString() })
            : t("pro.inactive");
        const slots = ["frame", "nick_color", "ai_skin"]
            .map((slot) => {
                const options = player.wardrobe
                    .filter((item) => item.slot === slot)
                    .map((item) => {
                        const label = item.available
                            ? t(`item.${item.code}`)
                            : `${t(`item.${item.code}`)} · ${item.stars ? `${item.stars} ⭐` : "Pro"}`;
                        const selected = player.cosmetics[slot] === item.code ? "selected" : "";
                        return `<option value="${item.code}" ${item.available ? "" : "disabled"} ${selected}>${esc(label)}</option>`;
                    })
                    .join("");
                return `<li><div class="grow hint">${esc(t(`slot.${slot}`))}</div>
                    <select data-slot="${slot}"><option value="">${esc(t("cosmetic.none"))}</option>${options}</select></li>`;
            })
            .join("");
        return `<h2>${esc(t("pro.title"))}</h2>
            <p class="hint">${esc(status)}</p>
            <button class="primary" id="open-shop">${esc(t("pro.buy"))}</button>
            <h2>${esc(t("cosmetics.title"))}</h2>
            <ul class="list">${slots}</ul>`;
    }

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
            ${proCard(player)}
            <h2>${esc(t("share.title"))}</h2>
            ${seasonSwitch()}
            <p class="hint">${esc(t("share.hint"))}</p>
            <button class="primary" id="share">${esc(t("share.button"))}</button>
            <h2>${esc(t("profile.badges"))}</h2>
            <ul class="list">${badges}</ul>`;
        bindSeasonSwitch();
        $("#share").onclick = share;
        $("#open-shop").onclick = openShop;
        screen.querySelectorAll("[data-slot]").forEach((select) => {
            select.onchange = async () => {
                try {
                    state.me = await api("/game/me", { method: "PATCH", body: { [select.dataset.slot]: select.value || null } });
                    toast(t("saved"));
                } catch (error) {
                    toast(errorText(error));
                }
                go("profile");
            };
        });
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
