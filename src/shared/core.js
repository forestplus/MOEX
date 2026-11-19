'use strict';
/*
 * Общее ядро страниц тепловой карты MOEX.
 * Подключается в исходники директивой:  //@import shared/core.js
 * (build_protected.js встраивает файл при сборке).
 *
 * Здесь только то, что реально нужно нескольким страницам:
 * DOM-хелперы, fetch с таймаутом/повторами, форматирование чисел и дат.
 */

const Core = (() => {

    /* ---------- DOM ---------- */

    function mk(tag, cls, text) {
        const el = document.createElement(tag);
        if (cls) el.className = cls;
        if (text !== undefined && text !== null) el.textContent = text;
        return el;
    }

    /* ---------- сеть ---------- */

    async function fetchWithTimeout(url, { timeout = 15000, ...opts } = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeout);
        try {
            return await fetch(url, { cache: 'no-store', signal: controller.signal, ...opts });
        } finally {
            clearTimeout(timer);
        }
    }

    async function fetchJson(url, { retries = 2, timeout = 15000 } = {}) {
        let lastErr = null;
        for (let i = 0; i <= retries; i++) {
            try {
                const r = await fetchWithTimeout(url, { timeout });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return await r.json();
            } catch (e) {
                lastErr = e.name === 'AbortError' ? new Error('таймаут') : e;
                if (i < retries) await new Promise(res => setTimeout(res, 800 * (i + 1)));
            }
        }
        throw lastErr;
    }

    /* ---------- форматирование ---------- */

    const nf2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });

    function fmtNum(v, dec = 2) {
        if (v === null || v === undefined || !Number.isFinite(v)) return '—';
        return new Intl.NumberFormat('ru-RU', { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(v);
    }

    function fmtRub(v, dec = 2) {
        if (v === null || v === undefined || !Number.isFinite(v)) return '—';
        return fmtNum(v, dec) + ' ₽';
    }

    /* Компактно: 1,23 млн ₽ / 4,56 млрд ₽ */
    function fmtMoney(v) {
        if (v === null || v === undefined || !Number.isFinite(v)) return '—';
        const a = Math.abs(v);
        const sign = v < 0 ? '−' : '';
        if (a >= 1e9) return `${sign}${fmtNum(a / 1e9)} млрд ₽`;
        if (a >= 1e6) return `${sign}${fmtNum(a / 1e6)} млн ₽`;
        if (a >= 1e3) return `${sign}${nf0.format(a)} ₽`;
        return `${sign}${fmtNum(a)} ₽`;
    }

    function fmtPct(v, withSign = true) {
        if (v === null || v === undefined || !Number.isFinite(v)) return '—';
        const s = withSign && v > 0 ? '+' : '';
        return `${s}${fmtNum(v)} %`;
    }

    function fmtSignedRub(v) {
        if (v === null || v === undefined || !Number.isFinite(v)) return '—';
        return (v > 0 ? '+' : v < 0 ? '−' : '') + fmtMoney(Math.abs(v));
    }

    function fmtQty(v) {
        if (v === null || v === undefined || !Number.isFinite(v)) return '—';
        return nf0.format(v);
    }

    /* ---------- даты ---------- */

    function humanDateTime(iso) {
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return '—';
        return d.toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' });
    }

    /* ---------- прочее ---------- */

    function plClass(v) { return v > 0 ? 'pos' : v < 0 ? 'neg' : ''; }

    function setStatus(el, cls, text) {
        el.className = 'status' + (cls ? ' ' + cls : '');
        el.textContent = text;
    }

    return {
        mk, fetchJson, fetchWithTimeout,
        fmtNum, fmtRub, fmtMoney, fmtPct, fmtSignedRub, fmtQty,
        humanDateTime, plClass, setStatus
    };
})();
