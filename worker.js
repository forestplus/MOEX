/*
 * Cloudflare Worker: свой CORS-прокси для страниц тепловой карты.
 * Нужен, если публичные прокси недоступны (дивиденды, новости, описание компаний).
 *
 * Как поставить (бесплатно):
 *   1. dash.cloudflare.com → Workers & Pages → Create → Create Worker → Deploy.
 *   2. Edit code → вставить этот файл целиком → Deploy.
 *   3. Адрес воркера вида https://имя.ваш-аккаунт.workers.dev
 *   4. На странице «Избранное» → блок «Прокси для сторонних данных» → вставить
 *      https://имя.ваш-аккаунт.workers.dev/?url={url} → Сохранить → Проверить.
 *
 * Воркер пускает только перечисленные сайты и только запросы с вашего адреса страницы.
 */
const ALLOWED_ORIGINS = ['https://forestplus.github.io'];   // ваш адрес на GitHub Pages
const ALLOWED_HOSTS = [
    'smart-lab.ru', 'news.google.com', 'rssexport.rbc.ru', 'www.interfax.ru', 'www.kommersant.ru',
    'www.vedomosti.ru', 'www.finam.ru', 'ru.investing.com', 'tass.ru', 'ria.ru'
];

export default {
    async fetch(request) {
        const origin = request.headers.get('Origin') || '';
        const cors = {
            'Access-Control-Allow-Origin': ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0],
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Access-Control-Allow-Headers': '*',
            'Vary': 'Origin'
        };
        if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
        if (origin && !ALLOWED_ORIGINS.includes(origin)) return new Response('forbidden origin', { status: 403, headers: cors });

        const target = new URL(request.url).searchParams.get('url');
        let u;
        try { u = new URL(target); } catch (_) { return new Response('bad url', { status: 400, headers: cors }); }
        if (u.protocol !== 'https:' || !ALLOWED_HOSTS.includes(u.hostname)) {
            return new Response('host not allowed', { status: 403, headers: cors });
        }

        const r = await fetch(u.toString(), {
            headers: {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1',
                'Accept': 'text/html,application/xhtml+xml,application/xml,application/rss+xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.9'
            },
            cf: { cacheTtl: 600, cacheEverything: true }
        });
        const headers = new Headers(r.headers);
        Object.entries(cors).forEach(([k, v]) => headers.set(k, v));
        headers.delete('content-security-policy');
        headers.delete('set-cookie');
        return new Response(r.body, { status: r.status, headers });
    }
};
