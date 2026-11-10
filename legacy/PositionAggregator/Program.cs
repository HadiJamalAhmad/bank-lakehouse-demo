// Legacy position aggregation job (the "before" of the migration).
//
//   dotnet run -- <trades.csv> <fx_rates.csv> <positions.csv>
//
// Business rules, as the legacy job implements them:
//   1. A trade can be amended: only its latest version counts.
//   2. Cancelled trades (latest version CANCELLED) are dropped.
//   3. Notional = quantity * price, converted to CHF with the FX rate of the
//      trade date, or the most recent earlier rate (no rate at all is an error).
//      CHF trades use a rate of 1.
//   4. Each trade's CHF notional is rounded to 2 decimals with Math.Round:
//      for decimal this is banker's rounding (MidpointRounding.ToEven).
//   5. Positions per (counterparty, instrument): net quantity (BUY +, SELL -),
//      gross CHF notional (sum of rounded notionals), number of trades.
using System.Globalization;

var inv = CultureInfo.InvariantCulture;
if (args.Length != 3)
{
    Console.Error.WriteLine("usage: PositionAggregator <trades.csv> <fx_rates.csv> <positions.csv>");
    return 2;
}

// ---- FX rates: currency -> sorted (date, rate)
var fx = new Dictionary<string, List<(DateOnly Date, decimal Rate)>>();
foreach (var line in File.ReadLines(args[1]).Skip(1))
{
    var f = line.Split(',');
    var ccy = f[0];
    if (!fx.TryGetValue(ccy, out var list)) fx[ccy] = list = new();
    list.Add((DateOnly.ParseExact(f[1], "yyyy-MM-dd", inv), decimal.Parse(f[2], inv)));
}
foreach (var list in fx.Values) list.Sort((a, b) => a.Date.CompareTo(b.Date));

decimal RateOn(string ccy, DateOnly day)
{
    if (ccy == "CHF") return 1m;
    if (!fx.TryGetValue(ccy, out var list))
        throw new InvalidDataException($"no FX rates for {ccy}");
    decimal? found = null;
    foreach (var (d, r) in list)
    {
        if (d > day) break;
        found = r;
    }
    return found ?? throw new InvalidDataException($"no FX rate for {ccy} on or before {day:yyyy-MM-dd}");
}

// ---- trades: keep the latest version of each trade
var latest = new Dictionary<string, Trade>();
foreach (var line in File.ReadLines(args[0]).Skip(1))
{
    var f = line.Split(',');
    var t = new Trade(
        TradeId: f[0],
        Version: int.Parse(f[1], inv),
        TradeDate: DateOnly.ParseExact(f[2], "yyyy-MM-dd", inv),
        CounterpartyId: f[3],
        InstrumentId: f[4],
        Side: f[5],
        Quantity: long.Parse(f[6], inv),
        Price: decimal.Parse(f[7], inv),
        Currency: f[8],
        Status: f[9]);
    if (!latest.TryGetValue(t.TradeId, out var prev) || t.Version > prev.Version)
        latest[t.TradeId] = t;
}

// ---- aggregate
var positions = new SortedDictionary<(string Cpty, string Instr), Position>();
foreach (var t in latest.Values)
{
    if (t.Status == "CANCELLED") continue;
    var notionalChf = Math.Round(t.Quantity * t.Price * RateOn(t.Currency, t.TradeDate), 2);
    var key = (t.CounterpartyId, t.InstrumentId);
    if (!positions.TryGetValue(key, out var p)) positions[key] = p = new Position();
    p.NetQuantity += t.Side == "BUY" ? t.Quantity : -t.Quantity;
    p.GrossNotionalChf += notionalChf;
    p.TradeCount += 1;
}

using (var w = new StreamWriter(args[2]))
{
    w.WriteLine("counterparty_id,instrument_id,net_quantity,gross_notional_chf,trade_count");
    foreach (var ((cpty, instr), p) in positions)
        w.WriteLine(string.Join(',', cpty, instr, p.NetQuantity.ToString(inv),
            p.GrossNotionalChf.ToString("0.00", inv), p.TradeCount.ToString(inv)));
}
Console.WriteLine($"{latest.Count} trades read, {positions.Count} positions written to {args[2]}");
return 0;

record Trade(string TradeId, int Version, DateOnly TradeDate, string CounterpartyId,
             string InstrumentId, string Side, long Quantity, decimal Price,
             string Currency, string Status);

class Position
{
    public long NetQuantity;
    public decimal GrossNotionalChf;
    public int TradeCount;
}
