:root{
  --max:1600px;
  --bg:#f6f7fb;
  --card:#ffffff;
  --text:#0f172a;
  --muted:#64748b;
  --line:#e5e7eb;
  --blue:#2563eb;
  --blueSoft:#e6f0ff;
}

*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0;
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
  background:var(--bg);
  color:var(--text);
}

/* Topbar */
.Topbar{
  position:sticky;
  top:0;
  z-index:50;
  background:rgba(255,255,255,.92);
  backdrop-filter: blur(10px);
  border-bottom:1px solid var(--line);
}
.TopbarInner{
  max-width:var(--max);
  margin:0 auto;
  padding:10px 14px;
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
}
.Brand{display:flex;align-items:baseline;gap:8px}
.BrandLink{
  text-decoration:none;
  color:var(--text);
  font-weight:900;
}
.BrandSub{color:var(--muted);font-size:12px}

.MegaNav{display:flex;gap:8px;flex-wrap:wrap}
.NavLink{
  text-decoration:none;
  color:var(--muted);
  font-weight:800;
  padding:8px 10px;
  border-radius:12px;
}
.NavLink:hover{background:#f1f5f9;color:var(--text)}
.NavLink.Active{background:#eef2ff;color:#1e40af}

.TopSearch{position:relative;min-width:260px}
.Input{
  width:100%;
  border:1px solid var(--line);
  border-radius:12px;
  padding:10px 12px;
  outline:none;
}
.Input:focus{border-color:#c7d2fe; box-shadow:0 0 0 3px rgba(99,102,241,.15)}

/* Suggest dropdown */
.Suggest{
  position:absolute;
  top:calc(100% + 6px);
  left:0; right:0;
  background:#fff;
  border:1px solid var(--line);
  border-radius:14px;
  box-shadow:0 18px 40px rgba(15,23,42,.12);
  overflow:hidden;
  z-index:80;
}
.SuggestWide{max-width:720px}
.SugItem{
  padding:10px 12px;
  cursor:pointer;
  display:flex;
  justify-content:space-between;
  gap:10px;
}
.SugItem:hover{background:#f8fafc}
.SugLeft{font-weight:900}
.SugRight{color:var(--muted);font-size:12px}

/* Common */
.WideWrap{
  max-width:var(--max);
  margin:14px auto;
  padding:0 14px 110px 14px;
}

.Card{
  background:var(--card);
  border:1px solid var(--line);
  border-radius:16px;
  box-shadow: 0 10px 30px rgba(15,23,42,.04);
}
.CardHeader{padding:16px 16px 10px 16px}
.CardBody{padding:0 16px 16px 16px}
.H1{margin:0;font-size:24px}
.H2{margin:14px 0 8px 0;font-size:16px}
.Muted{color:var(--muted)}
.Small{font-size:12px}
.Status{
  margin-top:10px;
  padding:10px 12px;
  border-radius:12px;
  background:#f1f5f9;
  font-size:13px;
}

.Btn{
  border:1px solid var(--line);
  background:#fff;
  color:var(--text);
  border-radius:12px;
  padding:10px 12px;
  font-weight:800;
  cursor:pointer;
}
.Btn:hover{background:#f8fafc}
.Btn:disabled{opacity:.55;cursor:not-allowed}
.BtnPrimary{
  border-color:#c7d2fe;
  background:#eef2ff;
  color:#1e40af;
}
.BtnGhost{background:#f8fafc}

.Row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.RowSpace{display:flex;gap:10px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}
.P{line-height:1.6}

/* Home hero search */
.HeroSearchCard{
  background:linear-gradient(180deg,#ffffff 0%, #f8fafc 100%);
  border:1px solid var(--line);
  border-radius:20px;
  padding:18px;
  margin-bottom:14px;
}
.HeroInner{max-width:980px;margin:0 auto}
.HeroTitle{margin:0 0 10px 0;font-size:28px;letter-spacing:-.3px}
.HeroSearch{position:relative}
.HeroInput{
  width:100%;
  padding:16px 16px;
  border-radius:18px;
  border:1px solid var(--line);
  font-size:16px;
  outline:none;
}
.HeroInput:focus{border-color:#c7d2fe; box-shadow:0 0 0 4px rgba(99,102,241,.12)}

.CountriesRow{margin-top:14px}
.CountriesTitle{color:var(--muted);font-weight:800;font-size:12px;margin-bottom:8px}
.CountryChips{display:flex;flex-wrap:wrap;gap:8px}
.Chip{
  border:1px solid var(--line);
  background:#fff;
  border-radius:999px;
  padding:8px 10px;
  font-weight:900;
  cursor:pointer;
}
.Chip:hover{background:#f8fafc}

/* Home main grid */
.MainGrid{
  display:grid;
  grid-template-columns: 520px 1fr;
  gap:14px;
  align-items:start;
}
.LeftPanel{display:flex;flex-direction:column;gap:14px}
.RightPanel{display:flex;flex-direction:column;gap:14px}

.CityList{list-style:none;padding:0;margin:10px 0 0 0;display:grid;gap:10px}
.CityBtn{
  width:100%;
  text-align:left;
  border:1px solid var(--line);
  background:#fff;
  padding:10px 12px;
  border-radius:14px;
  cursor:pointer;
}
.CityBtn:hover{background:#f8fafc}
.CityMeta{color:var(--muted);font-size:12px;margin-top:4px}

.MapCard .MapBox, .MapBox{
  width:100%;
  height:520px;
  border-top:1px solid var(--line);
  border-bottom:1px solid var(--line);
}

/* City page / country page grids */
.CityPageGrid{
  display:grid;
  grid-template-columns: 1.2fr .8fr;
  gap:14px;
  align-items:start;
}
.MapCardSticky{position:sticky;top:72px}

/* simple grids */
.Grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.CityItemBig{
  border:1px solid var(--line);
  border-radius:14px;
  padding:10px 12px;
  background:#fff;
}
.CityLink{text-decoration:none;color:var(--text);font-weight:900}

/* FAQ */
.Hr{border:none;border-top:1px solid var(--line);margin:16px 0}
.Faq details{
  border:1px solid var(--line);
  border-radius:14px;
  padding:10px 12px;
  background:#fff;
  margin:10px 0;
}
.Faq summary{cursor:pointer;font-weight:900}
.FaqBody{margin-top:8px;line-height:1.5}

/* Accordion placeholders (city page JS uses these classes) */
.Accordion{display:grid;gap:10px;margin-top:10px}

/* Sticky player */
.StickyPlayer{
  position:fixed;left:0;right:0;bottom:0;
  z-index:1000;
  background:rgba(255,255,255,.96);
  backdrop-filter: blur(10px);
  border-top:1px solid var(--line);
}
.StickyInner{max-width:var(--max);margin:0 auto;padding:10px 14px;display:flex;flex-direction:column;gap:8px}
.StickyRow{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.NowTitle{font-weight:900;max-width:min(900px,80vw);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.NowMeta{color:var(--muted);font-size:12px}
.Controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.ProgressText{font-weight:900;font-size:12px;color:#334155}
.Progress{width:min(820px, 92vw)}

.IconBtn{
  width:40px;height:40px;
  border-radius:12px;
  border:1px solid var(--line);
  background:#fff;
  cursor:pointer;
  font-size:18px;
}
.IconBtn:hover{background:#f8fafc}
.IconBtn:disabled{opacity:.55;cursor:not-allowed}

/* Mobile */
@media (max-width: 1100px){
  .MainGrid{grid-template-columns: 1fr}
  .MapCardSticky{position:relative;top:auto}
  .Grid2{grid-template-columns:1fr}
  .TopSearch{min-width:180px}
}