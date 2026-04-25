export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();

  const { symbol, range = '3mo', interval = '1d' } = req.query;
  if (!symbol) return res.status(400).json({ error: 'symbol is required' });

  const ySym = encodeURIComponent(symbol);
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${ySym}?range=${range}&interval=${interval}&includePrePost=true`;

  try {
    const response = await fetch(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      const url2 = url.replace('query1', 'query2');
      const r2 = await fetch(url2, { headers: { 'User-Agent': 'Mozilla/5.0' } });
      if (!r2.ok) return res.status(r2.status).json({ error: `Yahoo error: ${r2.status}` });
      const data2 = await r2.json();
      return res.status(200).json(data2);
    }

    const data = await response.json();
    res.setHeader('Cache-Control', 's-maxage=300, stale-while-revalidate=600');
    return res.status(200).json(data);
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
}
