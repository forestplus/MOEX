#!/usr/bin/env node
/*
 * Шифрует страницы паролем и собирает защищённые файлы.
 *
 * Использование:
 *   node build_protected.js "<логин>" "<пароль>" src/index.src.html index.html src/bonds.src.html bonds.html
 *
 * или через переменные окружения (пароль не попадёт в историю команд):
 *   MX_LOGIN=... MX_PASSWORD=... node build_protected.js src/index.src.html index.html src/bonds.src.html bonds.html
 *
 * Все страницы одного запуска шифруются ОДНИМ ключом: после входа на одной странице
 * вторая открывается без повторного ввода (пока открыта вкладка).
 *
 * В опубликованных файлах нет ни логина, ни пароля, ни его хэша — только зашифрованный
 * текст (AES-256-GCM, ключ из PBKDF2-SHA256, 600 000 итераций). Неверный пароль просто
 * не расшифровывает страницу.
 *
 * ВАЖНО: исходники (src/*.src.html) и этот скрипт в публичный репозиторий не публиковать.
 */
'use strict';

const fs = require('fs');
const crypto = require('crypto');

const ITER = 600000;

let args = process.argv.slice(2);
let login = process.env.MX_LOGIN;
let password = process.env.MX_PASSWORD;
if (!login || !password) {
    login = args.shift();
    password = args.shift();
}
if (!login || !password || args.length < 2 || args.length % 2) {
    console.error('Использование: node build_protected.js "<логин>" "<пароль>" <src1> <out1> [<src2> <out2> ...]');
    process.exit(1);
}

const SHELL = `<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex,nofollow">
<title>Вход</title>
<style>
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
       background: #f0f0f0; font-family: Arial, Helvetica, sans-serif; padding: 16px; }
.box { width: 100%; max-width: 340px; background: #fff; padding: 22px 20px 20px; border-radius: 12px;
       box-shadow: 0 2px 14px rgba(0,0,0,.12); }
h1 { margin: 0 0 14px; font-size: 20px; color: #222; }
label { display: block; font-size: 12px; color: #666; margin: 10px 0 4px; }
input[type=text], input[type=password] { width: 100%; padding: 10px 12px; border: 1px solid #ccc; border-radius: 8px; font-size: 16px; }
.cap { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
canvas { border: 1px solid #ddd; border-radius: 8px; width: 100%; max-width: 240px; height: auto; background: #eef2f7; }
.cap button { border: 1px solid #ccc; background: #fff; border-radius: 8px; padding: 8px 10px; font-size: 16px; cursor: pointer; }
.go { width: 100%; margin-top: 16px; padding: 12px; border: none; border-radius: 8px; background: #2e7d32;
      color: #fff; font-size: 16px; cursor: pointer; }
.go:disabled { opacity: .6; cursor: wait; }
.msg { min-height: 18px; margin-top: 10px; font-size: 13px; color: #c62828; }
.hint { font-size: 11px; color: #888; margin-top: 4px; }
</style>
</head>
<body>
<div class="box">
  <h1>Вход</h1>
  <form id="f" autocomplete="on">
    <label for="u">Логин</label>
    <input id="u" type="text" autocomplete="username" autocapitalize="none" spellcheck="false">
    <label for="w">Пароль</label>
    <input id="w" type="password" autocomplete="current-password">
    <label for="c">Проверка: введите 6 цифр и 1 букву с картинки</label>
    <div class="cap">
      <canvas id="cv" width="240" height="72"></canvas>
      <button type="button" id="rf" title="Другая картинка">↻</button>
    </div>
    <input id="c" type="text" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="7" style="margin-top:8px">
    <div class="hint">Цифры без 0 и 1, буква латинская; регистр не важен.</div>
    <button class="go" id="go" type="submit">Войти</button>
    <div class="msg" id="m"></div>
  </form>
</div>
<script id="p" type="text/plain">__PAYLOAD__</script>
<script>
(function () {
'use strict';
var SALT = '__SALT__', ITER = __ITER__, SK = 'mx_k';
var $ = function (id) { return document.getElementById(id); };
var payloadB64 = $('p').textContent.replace(/\\s+/g, '');

function fromB64(s) { var b = atob(s), a = new Uint8Array(b.length); for (var i = 0; i < b.length; i++) a[i] = b.charCodeAt(i); return a; }
function toB64(a) { var s = ''; for (var i = 0; i < a.length; i++) s += String.fromCharCode(a[i]); return btoa(s); }
function msg(t) { $('m').textContent = t || ''; }

async function openWith(keyBytes) {
    var key = await crypto.subtle.importKey('raw', keyBytes, 'AES-GCM', false, ['decrypt']);
    var data = fromB64(payloadB64);
    var plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: data.slice(0, 12) }, key, data.slice(12));
    var html = new TextDecoder().decode(plain);
    document.open();
    document.write(html);
    document.close();
}

async function derive(login, pass) {
    var enc = new TextEncoder();
    var km = await crypto.subtle.importKey('raw', enc.encode(login + ':' + pass), 'PBKDF2', false, ['deriveBits']);
    var bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', salt: fromB64(SALT), iterations: ITER, hash: 'SHA-256' }, km, 256);
    return new Uint8Array(bits);
}

/* ---- капча: 6 цифр + 1 буква в случайном порядке ---- */
var LET = 'ABCDEFGHJKLMNPQRSTUVWXYZ', DIG = '23456789', answer = '';
function rnd(n) { var a = new Uint32Array(1); crypto.getRandomValues(a); return a[0] % n; }
function drawCaptcha(ch) {
    var cv = $('cv'), ctx = cv.getContext('2d'), w = cv.width, h = cv.height, i;
    var g = ctx.createLinearGradient(0, 0, w, h);
    g.addColorStop(0, '#eef2f7'); g.addColorStop(1, '#dfe7ef');
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    for (i = 0; i < 7; i++) {
        ctx.strokeStyle = 'hsl(' + rnd(360) + ',40%,60%)'; ctx.lineWidth = 1 + rnd(2);
        ctx.beginPath(); ctx.moveTo(rnd(w), rnd(h)); ctx.bezierCurveTo(rnd(w), rnd(h), rnd(w), rnd(h), rnd(w), rnd(h)); ctx.stroke();
    }
    for (i = 0; i < 140; i++) {
        ctx.fillStyle = 'hsl(' + rnd(360) + ',40%,55%)'; ctx.fillRect(rnd(w), rnd(h), 2, 2);
    }
    ctx.textBaseline = 'middle';
    for (i = 0; i < ch.length; i++) {
        ctx.save();
        ctx.translate(18 + i * 31, 36 + (rnd(13) - 6));
        ctx.rotate((rnd(70) - 35) / 100);
        ctx.font = 'bold ' + (30 + rnd(8)) + 'px Arial';
        ctx.fillStyle = 'hsl(' + rnd(360) + ',55%,28%)';
        ctx.fillText(ch[i], 0, 0);
        ctx.restore();
    }
    for (i = 0; i < 4; i++) {
        ctx.strokeStyle = 'rgba(40,40,40,.45)'; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(0, rnd(h)); ctx.lineTo(w, rnd(h)); ctx.stroke();
    }
}
function newCaptcha() {
    var ch = [], i;
    for (i = 0; i < 6; i++) ch.push(DIG.charAt(rnd(DIG.length)));
    ch.push(LET.charAt(rnd(LET.length)));
    for (i = ch.length - 1; i > 0; i--) { var k = rnd(i + 1), t = ch[i]; ch[i] = ch[k]; ch[k] = t; }
    answer = ch.join('');
    drawCaptcha(ch);
    $('c').value = '';
}

/* ---- вход ---- */
var fails = 0, lockUntil = 0;
$('rf').addEventListener('click', newCaptcha);
$('f').addEventListener('submit', async function (e) {
    e.preventDefault();
    if (typeof crypto === 'undefined' || !crypto.subtle) { msg('Нужен защищённый адрес (https://).'); return; }
    var wait = Math.ceil((lockUntil - Date.now()) / 1000);
    if (wait > 0) { msg('Слишком много попыток. Подождите ' + wait + ' с.'); return; }
    if ($('c').value.trim().toUpperCase() !== answer) { msg('Неверная проверка с картинки.'); newCaptcha(); return; }
    var login = $('u').value, pass = $('w').value;
    if (!login || !pass) { msg('Введите логин и пароль.'); return; }

    $('go').disabled = true; msg('Проверка...');
    try {
        var bytes = await derive(login, pass);
        try { sessionStorage.setItem(SK, toB64(bytes)); } catch (_) {}
        await openWith(bytes);
    } catch (err) {
        try { sessionStorage.removeItem(SK); } catch (_) {}
        fails++;
        if (fails >= 3) lockUntil = Date.now() + Math.min(60, Math.pow(2, fails - 2)) * 1000;
        msg('Неверный логин или пароль.');
        $('w').value = '';
        newCaptcha();
        $('go').disabled = false;
    }
});

newCaptcha();

var saved = null;
try { saved = sessionStorage.getItem(SK); } catch (_) {}
if (saved) {
    openWith(fromB64(saved)).catch(function () { try { sessionStorage.removeItem(SK); } catch (_) {} });
}
})();
</script>
</body>
</html>
`;

const salt = crypto.randomBytes(16);
const keyBytes = crypto.pbkdf2Sync(login + ':' + password, salt, ITER, 32, 'sha256');

for (let i = 0; i < args.length; i += 2) {
    const [src, out] = [args[i], args[i + 1]];
    const html = fs.readFileSync(src, 'utf8');
    const iv = crypto.randomBytes(12);
    const cipher = crypto.createCipheriv('aes-256-gcm', keyBytes, iv);
    const ct = Buffer.concat([cipher.update(html, 'utf8'), cipher.final()]);
    const payload = Buffer.concat([iv, ct, cipher.getAuthTag()]); // WebCrypto ждёт «шифртекст + тег»
    const shell = SHELL
        .replace('__PAYLOAD__', () => payload.toString('base64'))
        .replace('__SALT__', () => salt.toString('base64'))
        .replace('__ITER__', () => String(ITER));
    fs.writeFileSync(out, shell, 'utf8');
    console.log(`${src} -> ${out} (${Math.round(shell.length / 1024)} КБ)`);
}
