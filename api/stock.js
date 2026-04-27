export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  if (req.method === 'OPTIONS') return res.status(200).end();
  const { symbol = 'AAPL', range = '3mo', interval = '1d' } = req.query;
  const sym = symbol;
  const h = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Referer': 'https://finance.yahoo.com/',
  };
  for (const host of ['https://query1.finance.yahoo.com','https://query2.finance.yahoo.com']) {
    try {
      const r = await fetch(
        `${host}/v8/finance/chart/${sym}?range=${range}&interval=${interval}&includePrePost=false`,
        { headers: h }
      );
      if (!r.ok) continue;
      const d = await r.json();
      if (!d?.chart?.result?.[0]) continue;
      res.setHeader('Cache-Control', 's-maxage=900,stale-while-revalidate=1800');
      return res.status(200).json(d);
    } catch(e) { continue; }
  }
  return res.status(503).json({ error: 'unavailable' });
}
