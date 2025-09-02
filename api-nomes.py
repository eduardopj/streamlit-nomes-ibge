# -*- coding: utf-8 -*-
"""
IBGE • Nomes (Censo 2010) — App completo v5
- Mantém TODAS as abas e presets (Visão geral, Ranking, Série, Evoluções, Totais, Evolução global).
- Textos padronizados: "Top Nomes (N)".
- Evoluções reescrita (sem hacks de locals) + presets funcionais via session_state.
- HTTP com User-Agent e tentativas simples.
- KPIs de totais + "registros retornados" (linhas da API) por sexo.
- População Brasil (projeção) com mensagens claras.
"""

from typing import Any, Dict, List, Optional
import re
import time

import requests
import pandas as pd
import streamlit as st
import altair as alt

st.set_page_config(page_title="IBGE • Nomes (Censo 2010)", page_icon="📝", layout="wide")

API_NOMES = "https://servicodados.ibge.gov.br/api/v2/censos/nomes"
API_LOCALIDADES = "https://servicodados.ibge.gov.br/api/v1/localidades"
API_POP = "https://servicodados.ibge.gov.br/api/v1/projecoes/populacao"

# ----------------- Session defaults -----------------
if "theme_dark" not in st.session_state:
    st.session_state.theme_dark = False
if "evo_autorun" not in st.session_state:
    st.session_state.evo_autorun = False
if "evo_params" not in st.session_state:
    st.session_state.evo_params = {}
if "preset_uf" not in st.session_state:
    st.session_state.preset_uf = "SP"

# ----------------- HTTP helpers -----------------
def _http_get(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30) -> requests.Response:
    headers = {"User-Agent": "Mozilla/5.0 (IBGE-Nomes-Streamlit/edu-ads)"}
    last_exc: Optional[Exception] = None
    for i in range(3):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                return resp
        except Exception as e:
            last_exc = e
        time.sleep(0.5 * (i + 1))
    if last_exc:
        raise last_exc
    return requests.get(url, params=params, headers=headers, timeout=timeout)

@st.cache_data(show_spinner=False, ttl=1800)
def fetch_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    r = _http_get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

# ----------------- Localidades -----------------
@st.cache_data(show_spinner=False, ttl=86400)
def get_estados() -> pd.DataFrame:
    df = pd.DataFrame(fetch_json(f"{API_LOCALIDADES}/estados"))
    if df.empty: return df
    return df[["id", "sigla", "nome"]].sort_values("nome").reset_index(drop=True)

def get_localidade_id_por_sigla(sigla: str) -> Optional[str]:
    if not sigla: return None
    est = get_estados()
    row = est.loc[est["sigla"] == sigla.upper()]
    return None if row.empty else str(int(row.iloc[0]["id"]))

@st.cache_data(show_spinner=False, ttl=86400)
def get_municipios(sigla_uf: str) -> pd.DataFrame:
    uf_id = get_localidade_id_por_sigla(sigla_uf)
    if not uf_id:
        return pd.DataFrame(columns=["id_municipio", "municipio"])
    df = pd.DataFrame(fetch_json(f"{API_LOCALIDADES}/estados/{uf_id}/municipios"))
    if df.empty:
        return pd.DataFrame(columns=["id_municipio", "municipio"])
    df = df.rename(columns={"id": "id_municipio", "nome": "municipio"})
    return df[["id_municipio", "municipio"]].sort_values("municipio").reset_index(drop=True)

def get_sigla_por_id(localidade_id: str) -> Optional[str]:
    try:
        lid = int(localidade_id)
    except Exception:
        return None
    est = get_estados()
    row = est.loc[est["id"] == lid]
    return None if row.empty else row.iloc[0]["sigla"]

def get_municipio_id(sigla_uf: str, nome_municipio: str) -> Optional[str]:
    df = get_municipios(sigla_uf)
    if df.empty: return None
    nome = (nome_municipio or "").strip()
    if not nome: return None
    row = df[df["municipio"].str.casefold() == nome.casefold()]
    if row.empty:
        row = df[df["municipio"].str.contains(nome, case=False, na=False)]
        if row.empty:
            return None
    return str(int(row.iloc[0]["id_municipio"]))

# ----------------- População Brasil -----------------
@st.cache_data(show_spinner=False, ttl=1800)
def get_populacao_brasil() -> Dict[str, Any]:
    """Retorna {'ok': True, 'pop': int} ou {'ok': False, 'err': str}."""
    try:
        data = fetch_json(API_POP)
        pop = int(data["projecao"]["populacao"])
        return {"ok": True, "pop": pop}
    except Exception as e:
        return {"ok": False, "err": str(e)}

# ----------------- API de Nomes -----------------
def get_nome_por_decada(nome: str, sexo: Optional[str] = None, localidade: Optional[str] = None) -> pd.DataFrame:
    url = f"{API_NOMES}/{nome.strip().lower()}"
    params: Dict[str, Any] = {}
    if sexo in {"M", "F"}: params["sexo"] = sexo
    if localidade: params["localidade"] = localidade
    payload = fetch_json(url, params=params)
    if not payload: return pd.DataFrame()
    rows: List[Dict[str, Any]] = []
    item = payload[0]
    nm = item.get("nome")
    sx = item.get("sexo") or sexo or "Todos"
    for res in item.get("res", []):
        periodo = res.get("periodo")
        yrs = re.findall(r"\d{4}", str(periodo))
        start = int(yrs[0]) if yrs else None
        rows.append({"nome": nm or "", "sexo": sx, "periodo": periodo, "ano_inicio": start, "frequencia": res.get("frequencia")})
    df = pd.DataFrame(rows)
    if df.empty: return df
    df["frequencia"] = pd.to_numeric(df["frequencia"], errors="coerce")
    return df.sort_values("ano_inicio").reset_index(drop=True)

def get_ranking(decada: Optional[int] = None, sexo: Optional[str] = None, localidade: Optional[str] = None, qtd: Optional[int] = 20) -> pd.DataFrame:
    url = f"{API_NOMES}/ranking"
    params: Dict[str, Any] = {}
    if decada: params["decada"] = decada
    if sexo in {"M", "F"}: params["sexo"] = sexo
    if localidade: params["localidade"] = localidade
    if qtd: params["qtd"] = int(qtd)
    payload = fetch_json(url, params=params)
    try:
        res = payload[0]["res"]
    except Exception:
        return pd.DataFrame()
    df = pd.DataFrame(res)
    if "frequencia" in df.columns:
        df["frequencia"] = pd.to_numeric(df["frequencia"], errors="coerce")
    if "ranking" in df.columns and "rank" not in df.columns:
        df = df.rename(columns={"ranking": "rank"})
    if "rank" in df.columns:
        df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
    return df

def get_ranking_unified(decada: Optional[int], sexo: Optional[str], localidade: Optional[str], qtd: int) -> pd.DataFrame:
    df = get_ranking(decada, sexo, localidade, qtd)
    if not df.empty and len(df) >= qtd:
        return df.head(qtd)
    if sexo is None:
        df_m = get_ranking(decada, "M", localidade, qtd)
        df_f = get_ranking(decada, "F", localidade, qtd)
        if df_m.empty and df_f.empty: return df
        base = pd.concat([df_m.assign(sexo="M"), df_f.assign(sexo="F")], ignore_index=True)
        if "frequencia" in base.columns:
            agg = base.groupby("nome", as_index=False)["frequencia"].sum()
            agg = agg.sort_values("frequencia", ascending=False).head(qtd).reset_index(drop=True)
            agg["rank"] = range(1, len(agg) + 1)
            return agg
    return df.head(qtd) if not df.empty else df

def _series_freq_for_decade(names: List[str], decada: int, sexo: Optional[str], localidade: str, sleep: float = 0.0) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for nm in names:
        try:
            df = get_nome_por_decada(nm, sexo, localidade)
            if df.empty:
                rows.append({"nome": nm, "freq": 0}); continue
            f = df.loc[df["ano_inicio"] == decada, "frequencia"]
            freq = int(f.iloc[0]) if not f.empty else 0
            rows.append({"nome": nm, "freq": freq})
        except Exception:
            rows.append({"nome": nm, "freq": 0})
        if sleep: time.sleep(sleep)
    return pd.DataFrame(rows)

def growth_between_decades(dec_a: int, dec_b: int, sexo: Optional[str], localidade: str, topn: int = 200, set_mode: str = "intersect") -> pd.DataFrame:
    a = get_ranking(dec_a, sexo, localidade, topn).rename(columns={"frequencia": "freq_a", "rank": "rank_a"})
    b = get_ranking(dec_b, sexo, localidade, topn).rename(columns={"frequencia": "freq_b", "rank": "rank_b"})
    if set_mode == "intersect":
        if a.empty or b.empty: return pd.DataFrame()
        m = pd.merge(a[["nome","freq_a","rank_a"]], b[["nome","freq_b","rank_b"]], on="nome", how="inner")
    elif set_mode == "only_B":
        if b.empty: return pd.DataFrame()
        nomes_b = b["nome"].tolist()
        freqs_a = _series_freq_for_decade(nomes_b, dec_a, sexo, localidade)
        m = pd.merge(b[["nome","freq_b","rank_b"]], freqs_a.rename(columns={"freq":"freq_a"}), on="nome", how="left")
        m["rank_a"] = None
    else:  # only_A
        if a.empty: return pd.DataFrame()
        nomes_a = a["nome"].tolist()
        freqs_b = _series_freq_for_decade(nomes_a, dec_b, sexo, localidade)
        m = pd.merge(a[["nome","freq_a","rank_a"]], freqs_b.rename(columns={"freq":"freq_b"}), on="nome", how="left")
        m["rank_b"] = None
    if m.empty: return m
    m["freq_a"] = pd.to_numeric(m["freq_a"], errors="coerce").fillna(0).astype(int)
    m["freq_b"] = pd.to_numeric(m["freq_b"], errors="coerce").fillna(0).astype(int)
    m["delta"] = (m["freq_b"] - m["freq_a"]).astype(float)
    m["pct"] = m.apply(lambda r: (r["delta"]/r["freq_a"]*100.0) if r["freq_a"] else None, axis=1)
    m["delta_rank"] = m.apply(lambda r: (r["rank_a"]-r["rank_b"]) if (pd.notna(r.get("rank_a")) and pd.notna(r.get("rank_b"))) else None, axis=1)
    return m.sort_values("delta", ascending=False).reset_index(drop=True)

# ----------------- CSS + Altair theme -----------------
def css(dark: bool) -> str:
    if not dark:
        return """
        <style>
        #MainMenu, header, footer, [data-testid="stToolbar"], [data-testid="stDeployButton"], [data-testid="stStatusWidget"] { display:none!important; }
        .block-container { max-width: 1220px; padding-top:.8rem; padding-bottom:2rem; }
        .h-hero { display:flex; gap:12px; margin-bottom:.25rem; font-size:2rem; font-weight:800; }
        .h-caption { color:#6b7280; margin-bottom:.75rem;}
        .card { background:#fff; border:1px solid #e5e7eb; border-radius:14px; padding:18px 16px; box-shadow:0 1px 2px rgba(0,0,0,.03); margin-bottom:12px;}
        .right { display:flex; justify-content:flex-end; }
        .badge { display:inline-block; padding:2px 8px; border-radius:999px; border:1px solid #e5e7eb; margin-right:6px; background:#f8fafc;}
        .grid-uf, .grid-caps { display:grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 8px;}
        @media (max-width: 1200px){ .grid-uf, .grid-caps{ grid-template-columns: repeat(6, 1fr);} }
        @media (max-width: 900px){ .grid-uf, .grid-caps{ grid-template-columns: repeat(4, 1fr);} }
        .kpi { font-size:28px; font-weight:800; margin-bottom:-6px;}
        .kpi-sub { color:#6b7280; font-size:13px;}
        </style>
        """
    return """
    <style>
    :root { --bg:#0b1220; --fg:#e5e7eb; --muted:#9ca3af; --card:#111827; --border:#1f2937; }
    html, body, .block-container { background: var(--bg)!important; color: var(--fg)!important; }
    #MainMenu, header, footer, [data-testid="stToolbar"], [data-testid="stDeployButton"], [data-testid="stStatusWidget"] { display:none!important; }
    .block-container { max-width: 1220px; padding-top:.8rem; padding-bottom:2rem; }
    .h-hero { display:flex; gap:12px; margin-bottom:.25rem; font-size:2rem; font-weight:800; color:var(--fg);}
    .h-caption { color:var(--muted); margin-bottom:.75rem;}
    .card { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:18px 16px; box-shadow:none; margin-bottom:12px;}
    .right { display:flex; justify-content:flex-end; }
    .badge { display:inline-block; padding:2px 8px; border-radius:999px; border:1px solid var(--border); margin-right:6px; background:#0f172a; color:var(--fg);}
    .grid-uf, .grid-caps { display:grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 8px;}
    @media (max-width: 1200px){ .grid-uf, .grid-caps{ grid-template-columns: repeat(6, 1fr);} }
    @media (max-width: 900px){ .grid-uf, .grid-caps{ grid-template-columns: repeat(4, 1fr);} }
    </style>
    """

def _altair_theme(dark: bool):
    fg = "#e5e7eb" if dark else "#374151"
    grid = "#334155" if dark else "#e5e7eb"
    return {
        "config": {
            "background": "transparent",
            "view": {"strokeWidth": 0},
            "axis": {"labelColor": fg, "titleColor": fg, "gridColor": grid},
            "legend": {"labelColor": fg, "titleColor": fg},
            "title": {"color": fg},
        }
    }

def enable_altair_theme(dark: bool):
    alt.themes.register("ibge_dark", lambda: _altair_theme(True))
    alt.themes.register("ibge_light", lambda: _altair_theme(False))
    alt.themes.enable("ibge_dark" if dark else "ibge_light")

# -------------- Aux UI --------------
def show_filters(**kwargs):
    badges = []
    for k, v in kwargs.items():
        if v is None or v == "":
            continue
        badges.append(f'<span class="badge">{k}: {v}</span>')
    if badges:
        st.markdown("".join(badges), unsafe_allow_html=True)

def chart_serie_decadas(df: pd.DataFrame) -> alt.Chart:
    d = df.copy()
    d = d.dropna(subset=["ano_inicio", "frequencia"])
    d["ano_inicio"] = pd.to_numeric(d["ano_inicio"], errors="coerce").astype("Int64")
    d = d.dropna(subset=["ano_inicio"]).copy()
    d["decada"] = d["ano_inicio"].astype(int).astype(str)
    ordem = sorted(d["ano_inicio"].dropna().unique().tolist())
    ordem_labels = [str(int(x)) for x in ordem]
    return (
        alt.Chart(d)
        .mark_line(point=True)
        .encode(
            x=alt.X("decada:N", sort=ordem_labels, title="Década"),
            y=alt.Y("frequencia:Q", title="Frequência", axis=alt.Axis(format="~s")),
            color=alt.Color("nome:N", title="Nome"),
            tooltip=["nome", "periodo", "frequencia", "sexo"],
        )
        .properties(height=420)
    )

# ----------------- Presets (Regiões/Capitais) -----------------
REGIOES: Dict[str, List[str]] = {
    "Norte": ["AC", "AM", "AP", "PA", "RO", "RR", "TO"],
    "Nordeste": ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
    "Centro-Oeste": ["DF", "GO", "MT", "MS"],
    "Sudeste": ["ES", "MG", "RJ", "SP"],
    "Sul": ["PR", "RS", "SC"],
    "Amazônia Legal": ["AC", "AM", "AP", "PA", "RO", "RR", "TO", "MA", "MT"],
}

CAPITAIS: Dict[str, str] = {
    "Rio Branco": "AC", "Manaus": "AM", "Macapá": "AP", "Belém": "PA", "Porto Velho": "RO",
    "Boa Vista": "RR", "Palmas": "TO", "São Luís": "MA", "Teresina": "PI", "Fortaleza": "CE",
    "Natal": "RN", "João Pessoa": "PB", "Recife": "PE", "Maceió": "AL", "Aracaju": "SE",
    "Salvador": "BA", "Cuiabá": "MT", "Campo Grande": "MS", "Goiânia": "GO", "Brasília": "DF",
    "Vitória": "ES", "Belo Horizonte": "MG", "Rio de Janeiro": "RJ", "São Paulo": "SP",
    "Curitiba": "PR", "Florianópolis": "SC", "Porto Alegre": "RS",
}

def render_regional_preset(region: str, dec_a=1990, dec_b=2010, top=50):
    st.caption("Clique numa UF para montar a comparação e gerar o gráfico. As 'Capitais' abaixo se ajustam para a UF selecionada.")
    ufs = REGIOES[region]
    st.markdown('<div class="grid-uf">', unsafe_allow_html=True)
    cols = st.columns(8)
    for i, uf in enumerate(ufs):
        with cols[i % 8]:
            if st.button(uf, key=f"preset_{region}_{uf}_{dec_a}_{dec_b}", use_container_width=True):
                st.session_state.preset_uf = uf
                lid = get_localidade_id_por_sigla(uf)
                st.session_state.evo_params = {
                    "dec_a": dec_a, "dec_b": dec_b, "sexo": None,
                    "escopo": "UF", "localidade": lid, "top": top,
                    "conjunto": "intersect"
                }
                st.session_state.evo_autorun = True
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

def render_capitais_preset(dec_a=1990, dec_b=2010, top=50):
    estados = get_estados()
    uf_atual = st.session_state.get("preset_uf", "SP")
    st.caption("Escolha uma capital para montar a análise. Selecione a UF (ou use os botões de UFs acima).")
    uf_list = estados["sigla"].tolist()
    cuf1, _ = st.columns([2, 6])
    with cuf1:
        uf_sel = st.selectbox("UF para capitais", uf_list, index=uf_list.index(uf_atual) if uf_atual in uf_list else 0)
        if uf_sel != st.session_state.preset_uf:
            st.session_state.preset_uf = uf_sel

    caps = [nome for nome, uf in CAPITAIS.items() if uf == st.session_state.preset_uf]
    if not caps:
        st.info("Não há capitais definidas para esta UF."); return
    st.markdown('<div class="grid-caps">', unsafe_allow_html=True)
    cols = st.columns(8)
    for i, cap in enumerate(caps):
        with cols[i % 8]:
            if st.button(cap, key=f"preset_cap_{cap}_{dec_a}_{dec_b}", use_container_width=True):
                uf = st.session_state.preset_uf
                mid = get_municipio_id(uf, cap)
                if mid:
                    st.session_state.evo_params = {
                        "dec_a": dec_a, "dec_b": dec_b, "sexo": None,
                        "escopo": "Município", "localidade": mid, "top": top,
                        "conjunto": "intersect"
                    }
                    st.session_state.evo_autorun = True
                    st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

# ----------------- Header -----------------
col_h1, col_h2 = st.columns([6, 1])
with col_h1:
    st.markdown(
        '<div class="h-hero">📝 IBGE • Nomes (Censo 2010)</div>'
        '<div class="h-caption">Ranking, séries, evoluções e totais — API Nomes v2 do IBGE.</div>',
        unsafe_allow_html=True,
    )
with col_h2:
    st.toggle("🌗 Modo escuro", key="theme_dark")

st.markdown(css(st.session_state.theme_dark), unsafe_allow_html=True)
enable_altair_theme(st.session_state.theme_dark)

# ----------------- Tabs -----------------
tab_home, tab_rank, tab_serie, tab_evo, tab_totais, tab_global, tab_pop = st.tabs(
    ["🏠 Visão geral", "🏆 Ranking detalhado", "🔎 Série por nome", "📈 Evoluções", "👥 Totais (KPI)", "📊 Evolução global", "🇧🇷 População BR"]
)

# ---------- Visão geral ----------
with tab_home:
    st.subheader("Resumo rápido")
    estados = get_estados()
    with st.form("form_home"):
        st.markdown('<div class="card">', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            escopo = st.selectbox("Escopo", ["Brasil", "UF", "Município"], index=0)
        with c2:
            decadas = [None, 1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010]
            decada = st.selectbox("Década (opcional)", decadas, format_func=lambda x: "Todas" if x is None else str(x))
        with c3:
            localidade_val = "BR"; localidade_label = "Brasil"
            if escopo == "UF":
                uf = st.selectbox("UF", estados["sigla"].tolist(), index=0)
                localidade_val = str(int(estados.loc[estados["sigla"] == uf, "id"].iloc[0]))
                localidade_label = uf
            elif escopo == "Município":
                uf = st.selectbox("UF do município", estados["sigla"].tolist(), index=0, key="home_uf_m")
                mdf = get_municipios(uf)
                if mdf.empty:
                    st.warning("Não foi possível carregar municípios desta UF agora."); st.stop()
                mun = st.selectbox("Município", mdf["municipio"].tolist(), index=0)
                localidade_val = str(int(mdf.loc[mdf["municipio"] == mun, "id_municipio"].iloc[0]))
                localidade_label = f"{mun}/{uf}"
        st.markdown('<div class="right">', unsafe_allow_html=True)
        submit_home = st.form_submit_button("Atualizar resumo")
        st.markdown('</div></div>', unsafe_allow_html=True)

    if submit_home:
        show_filters(Escopo=escopo, Localidade=localidade_label, Década=("Todas" if decada is None else decada))
        c1, c2 = st.columns(2)
        def render_top(df: pd.DataFrame, titulo: str):
            st.markdown(f"**{titulo}**")
            if df.empty:
                st.info("Sem dados para este filtro."); return
            dfx = df.copy().head(10)
            if "frequencia" in dfx.columns: dfx = dfx.sort_values("frequencia", ascending=False)
            st.dataframe(dfx[[c for c in ["nome","frequencia","rank"] if c in dfx.columns]], use_container_width=True, hide_index=True)
            if "frequencia" in dfx.columns:
                dplot = dfx.sort_values("frequencia", ascending=True)
                ch = alt.Chart(dplot).mark_bar().encode(
                    x=alt.X("frequencia:Q", title="Frequência"),
                    y=alt.Y("nome:N", sort=None, title="Nome"),
                    tooltip=[c for c in ["nome","frequencia","rank"] if c in dplot.columns],
                ).properties(height=max(320, 24*len(dplot)))
                st.altair_chart(ch, use_container_width=True)
        try:
            df_m = get_ranking_unified(decada if decada else None, "M", localidade_val, 10)
            df_f = get_ranking_unified(decada if decada else None, "F", localidade_val, 10)
            with c1: render_top(df_m, "Top 10 Masculinos")
            with c2: render_top(df_f, "Top 10 Femininos")
        except Exception as e:
            st.error(f"Falha ao carregar resumo: {e}")

# ---------- Ranking ----------
with tab_rank:
    st.subheader("Ranking detalhado")
    estados = get_estados()
    with st.form("form_rank"):
        st.markdown('<div class="card">', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            escopo_r = st.selectbox("Escopo", ["Brasil", "UF", "Município"], index=0)
        with c2:
            decada_r = st.selectbox("Década (opcional)", [None,1930,1940,1950,1960,1970,1980,1990,2000,2010],
                                    format_func=lambda x: "Todas" if x is None else str(x))
        with c3:
            sexo_r = st.selectbox("Sexo", ["Todos","M","F"], index=0)
        c4, c5 = st.columns(2)
        with c4:
            qtd = st.slider("Top Nomes (N)", 10, 200, 20, 10,
                            help="N é a quantidade de nomes mais frequentes que a API retorna (ordenados por frequência).")
            ordenar = st.radio("Ordenar por", ["Frequência","Rank"], horizontal=True)
        with c5:
            localidade_val_r = "BR"; localidade_label_r = "Brasil"
            if escopo_r == "UF":
                uf_r = st.selectbox("UF", estados["sigla"].tolist(), index=0)
                localidade_val_r = str(int(estados.loc[estados["sigla"] == uf_r, "id"].iloc[0]))
                localidade_label_r = uf_r
            elif escopo_r == "Município":
                uf_r = st.selectbox("UF do município", estados["sigla"].tolist(), index=0)
                mdf_r = get_municipios(uf_r)
                if mdf_r.empty:
                    st.warning("Não foi possível carregar municípios desta UF agora."); st.stop()
                mun_r = st.selectbox("Município", mdf_r["municipio"].tolist(), index=0)
                localidade_val_r = str(int(mdf_r.loc[mdf_r["municipio"] == mun_r, "id_municipio"].iloc[0]))
                localidade_label_r = f"{mun_r}/{uf_r}"
        st.markdown('<div class="right">', unsafe_allow_html=True)
        submit_rank = st.form_submit_button("🔎 Buscar ranking")
        st.markdown('</div></div>', unsafe_allow_html=True)

    if submit_rank:
        show_filters(Escopo=escopo_r, Localidade=localidade_label_r, Sexo=sexo_r,
                     Década=("Todas" if decada_r is None else decada_r), TopNomes=qtd)
        try:
            df_rank = get_ranking_unified(decada_r if decada_r else None,
                                          None if sexo_r=="Todos" else sexo_r, localidade_val_r, int(qtd))
            if df_rank.empty:
                st.warning("Nenhum dado para esses filtros.")
            else:
                if ordenar=="Frequência" and "frequencia" in df_rank.columns:
                    df_rank = df_rank.sort_values("frequencia", ascending=False)
                elif "rank" in df_rank.columns:
                    df_rank = df_rank.sort_values("rank")
                st.success(f"Exibindo Top {len(df_rank)} nomes.")
                st.dataframe(df_rank.head(int(qtd)), use_container_width=True, hide_index=True)
                dplot = df_rank.copy().head(int(qtd))
                if "frequencia" in dplot.columns: dplot = dplot.sort_values("frequencia", ascending=True)
                ch = alt.Chart(dplot).mark_bar().encode(
                    x=alt.X("frequencia:Q", title="Frequência"),
                    y=alt.Y("nome:N", sort=None, title="Nome"),
                    tooltip=[c for c in ["nome","frequencia","rank"] if c in dplot.columns],
                ).properties(height=max(300, 18*len(dplot)))
                st.altair_chart(ch, use_container_width=True)
                st.download_button("⬇️ Baixar CSV", df_rank.head(int(qtd)).to_csv(index=False).encode("utf-8"),
                                   file_name="ranking_nomes_ibge.csv", mime="text/csv")
        except Exception as e:
            st.error(f"Falha ao processar ranking: {e}")

# ---------- Série por nome ----------
with tab_serie:
    st.subheader("Série por nome (frequência por década)")
    estados = get_estados()
    with st.form("form_serie"):
        st.markdown('<div class="card">', unsafe_allow_html=True)
        nomes_in = st.text_input("Nome(s) (separe por |)", "maria|joão|enzo")
        c1, c2, c3 = st.columns(3)
        with c1:
            sexo_s = st.selectbox("Sexo (opcional)", ["Todos","M","F"], index=0)
        with c2:
            escopo_s = st.selectbox("Escopo", ["Brasil","UF","Município"], index=0)
        with c3:
            localidade_s = "BR"; localidade_label_s = "Brasil"
            if escopo_s == "UF":
                uf_s = st.selectbox("UF", estados["sigla"].tolist(), index=0)
                localidade_s = str(int(estados.loc[estados["sigla"] == uf_s, "id"].iloc[0]))
                localidade_label_s = uf_s
            elif escopo_s == "Município":
                uf_s = st.selectbox("UF do município", estados["sigla"].tolist(), index=0)
                mdf_s = get_municipios(uf_s)
                if mdf_s.empty:
                    st.warning("Não foi possível carregar municípios desta UF agora."); st.stop()
                mun_s = st.selectbox("Município", mdf_s["municipio"].tolist(), index=0)
                localidade_s = str(int(mdf_s.loc[mdf_s["municipio"] == mun_s, "id_municipio"].iloc[0]))
                localidade_label_s = f"{mun_s}/{uf_s}"
        st.markdown('<div class="right">', unsafe_allow_html=True)
        submit_serie = st.form_submit_button("📈 Buscar série")
        st.markdown('</div></div>', unsafe_allow_html=True)

    if submit_serie:
        show_filters(Nomes=nomes_in, Sexo=sexo_s, Escopo=escopo_s, Localidade=localidade_label_s)
        try:
            nomes = [n.strip() for n in nomes_in.split("|") if n.strip()]
            all_df: List[pd.DataFrame] = []
            for nm in nomes:
                df_i = get_nome_por_decada(nm, None if sexo_s=="Todos" else sexo_s, localidade_s)
                if not df_i.empty: all_df.append(df_i)
            if not all_df:
                st.warning("Nenhum dado encontrado.")
            else:
                df = pd.concat(all_df, ignore_index=True)
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.caption("Décadas detectadas: " + ", ".join(sorted(df["ano_inicio"].dropna().astype(int).astype(str).unique())))
                st.altair_chart(chart_serie_decadas(df), use_container_width=True)
                st.download_button("⬇️ Baixar CSV da série", df.to_csv(index=False).encode("utf-8"),
                                   file_name="serie_nomes_ibge.csv", mime="text/csv")
        except Exception as e:
            st.error(f"Falha na série: {e}")

# ---------- Evoluções (com presets) ----------
with tab_evo:
    st.subheader("📈 Evoluções (comparação entre décadas)")
    estados = get_estados()

    with st.expander("Presets (Top 50 por UF/Município)"):
        c0, c1, c2 = st.columns(3)
        with c0:
            dec_a_p = st.selectbox("Década A", [1930,1940,1950,1960,1970,1980,1990,2000], index=6)
        with c1:
            dec_b_p = st.selectbox("Década B", [1940,1950,1960,1970,1980,1990,2000,2010], index=7)
        with c2:
            top_p = st.slider("Top Nomes (N)", 20, 200, 50, 10)

        st.markdown("### Regiões")
        region = st.selectbox("Selecione a região", list(REGIOES.keys()), index=1)
        render_regional_preset(region, dec_a_p, dec_b_p, top_p)

        st.divider()
        st.markdown("### Capitais (filtradas pela UF selecionada)")
        render_capitais_preset(dec_a_p, dec_b_p, top_p)

        st.divider()
        c3, c4 = st.columns(2)
        with c3:
            if st.button("1980 → 2000 (Brasil Top 50)"):
                st.session_state.evo_params = {"dec_a":1980,"dec_b":2000,"sexo":None,"escopo":"Brasil","localidade":"BR","top":50,"conjunto":"intersect"}
                st.session_state.evo_autorun = True; st.rerun()
        with c4:
            if st.button("2000 → 2010 (Brasil Top 50)"):
                st.session_state.evo_params = {"dec_a":2000,"dec_b":2010,"sexo":None,"escopo":"Brasil","localidade":"BR","top":50,"conjunto":"intersect"}
                st.session_state.evo_autorun = True; st.rerun()

    # parâmetros padrão da UI
    with st.form("form_evo"):
        st.markdown('<div class="card">', unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            dec_a = st.selectbox("Década A", [1930,1940,1950,1960,1970,1980,1990,2000], index=6, key="evo_a")
        with c2:
            dec_b = st.selectbox("Década B", [1940,1950,1960,1970,1980,1990,2000,2010], index=7, key="evo_b")
        with c3:
            sexo_e = st.selectbox("Sexo", ["Todos","M","F"], index=0, key="evo_sx")
        with c4:
            set_mode = st.selectbox("Conjunto", ["Interseção A∩B","Só Top de B","Só Top de A"], index=0, key="evo_set")
        c5, c6 = st.columns(2)
        with c5:
            escopo_e = st.selectbox("Escopo", ["Brasil","UF","Município"], index=0, key="evo_esc")
        with c6:
            top_e = st.slider("Top Nomes (N)", 20, 200, 100, 10, key="evo_n")
        localidade_e = "BR"; localidade_label_e = "Brasil"
        if escopo_e == "UF":
            uf_e = st.selectbox("UF", estados["sigla"].tolist(), index=0, key="evo_uf")
            localidade_e = str(int(estados.loc[estados["sigla"] == uf_e, "id"].iloc[0]))
            localidade_label_e = uf_e
        elif escopo_e == "Município":
            uf_e2 = st.selectbox("UF do município", estados["sigla"].tolist(), index=0, key="evo_uf_m")
            mdf_e = get_municipios(uf_e2)
            if mdf_e.empty:
                st.warning("Não foi possível carregar municípios desta UF agora."); st.stop()
            mun_e = st.selectbox("Município", mdf_e["municipio"].tolist(), index=0, key="evo_mun")
            localidade_e = str(int(mdf_e.loc[mdf_e["municipio"] == mun_e, "id_municipio"].iloc[0]))
            localidade_label_e = f"{mun_e}/{uf_e2}"
        st.markdown('<div class="right">', unsafe_allow_html=True)
        submit_evo = st.form_submit_button("Gerar evolução")
        st.markdown('</div></div>', unsafe_allow_html=True)

    # autorun via presets
    if st.session_state.evo_autorun:
        p = st.session_state.evo_params
        dec_a = p.get("dec_a", dec_a)
        dec_b = p.get("dec_b", dec_b)
        sexo_e = p.get("sexo", None)
        escopo_e = p.get("escopo", "Brasil")
        localidade_e = p.get("localidade", "BR")
        top_e = p.get("top", 50)
        set_mode = {"intersect":"Interseção A∩B","only_B":"Só Top de B","only_A":"Só Top de A"}.get(p.get("conjunto","intersect"), "Interseção A∩B")
        localidade_label_e = (get_sigla_por_id(localidade_e) or localidade_label_e)
        st.session_state.evo_autorun = False
        submit_evo = True

    if submit_evo:
        if dec_b <= dec_a:
            st.warning("Década B precisa ser maior que Década A.")
        else:
            sx = None if sexo_e in (None, "Todos") else sexo_e
            set_key = {"Interseção A∩B":"intersect","Só Top de B":"only_B","Só Top de A":"only_A"}[set_mode]
            show_filters(Décadas=f"{dec_a} → {dec_b}", Sexo=("Todos" if sx is None else sx),
                         Escopo=escopo_e, Localidade=localidade_label_e, TopNomes=top_e, Conjunto=set_mode)
            base = growth_between_decades(dec_a, dec_b, sx, localidade_e, topn=int(top_e), set_mode=set_key)
            if base.empty:
                st.error("A API não retornou dados cruzáveis para esses filtros. Tente reduzir N ou alterar sexo/escopo.")
            else:
                up = base.sort_values("delta", ascending=False).head(15)
                dn = base.sort_values("delta", ascending=True).head(15)
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**Quem mais cresceu ({dec_a} → {dec_b})**")
                    st.dataframe(up[["nome","freq_a","freq_b","delta","pct","delta_rank"]],
                                 use_container_width=True, hide_index=True)
                    ch1 = alt.Chart(up.sort_values("delta", ascending=True)).mark_bar().encode(
                        x=alt.X("delta:Q", title="Δ Frequência"),
                        y=alt.Y("nome:N", sort=None),
                        tooltip=["nome","freq_a","freq_b","delta",alt.Tooltip("pct:Q", format=".2f"),"delta_rank"],
                    ).properties(height=max(360, 22*len(up)))
                    st.altair_chart(ch1, use_container_width=True)
                with c2:
                    st.markdown(f"**Quem mais caiu ({dec_a} → {dec_b})**")
                    st.dataframe(dn[["nome","freq_a","freq_b","delta","pct","delta_rank"]],
                                 use_container_width=True, hide_index=True)
                    ch2 = alt.Chart(dn.sort_values("delta", ascending=True)).mark_bar().encode(
                        x=alt.X("delta:Q", title="Δ Frequência"),
                        y=alt.Y("nome:N", sort=None),
                        tooltip=["nome","freq_a","freq_b","delta",alt.Tooltip("pct:Q", format=".2f"),"delta_rank"],
                    ).properties(height=max(360, 22*len(dn)))
                    st.altair_chart(ch2, use_container_width=True)

# ---------- Totais (KPI claro + Registros) ----------
with tab_totais:
    st.subheader("👥 Totais — fácil de entender")
    estados = get_estados()

    with st.form("form_totais_kpi"):
        st.markdown('<div class="card">', unsafe_allow_html=True)
        c1, c2, c3 = st.columns([2,2,3])
        with c1:
            escopo_t = st.selectbox("Escopo", ["Brasil", "UF", "Município"], index=0)
        with c2:
            dec_t = st.selectbox("Década (para 'Ranking por década')",
                                 [None, 1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010],
                                 format_func=lambda x: "Todas" if x is None else str(x))
        with c3:
            modo_total = st.radio("O que mostrar agora?",
                                  ["Totais do ranking (Top Nomes)", "População Brasil (projeção IBGE)"],
                                  index=0, horizontal=False,
                                  help=("Totais do ranking somam as frequências dos nomes retornados pela API "
                                        "(até a quantidade N). População Brasil vem da projeção oficial do IBGE."))
        localidade_t = "BR"; localidade_label_t = "Brasil"
        if escopo_t == "UF":
            uf_t = st.selectbox("UF", estados["sigla"].tolist(), index=0)
            localidade_t = str(int(estados.loc[estados["sigla"] == uf_t, "id"].iloc[0]))
            localidade_label_t = uf_t
        elif escopo_t == "Município":
            uf_t = st.selectbox("UF do município", estados["sigla"].tolist(), index=0)
            mdf_t = get_municipios(uf_t)
            if mdf_t.empty:
                st.warning("Não foi possível carregar municípios desta UF agora."); st.stop()
            mun_t = st.selectbox("Município", mdf_t["municipio"].tolist(), index=0)
            localidade_t = str(int(mdf_t.loc[mdf_t["municipio"] == mun_t, "id_municipio"].iloc[0]))
            localidade_label_t = f"{mun_t}/{uf_t}"

        topn_t = None
        if modo_total == "Totais do ranking (Top Nomes)":
            topn_t = st.slider("Quantidade de nomes (N)", 20, 200, 200, 10,
                               help="Soma as frequências dos N nomes mais comuns de cada sexo.")
        st.markdown('<div class="right">', unsafe_allow_html=True)
        submit_tot = st.form_submit_button("Calcular")
        st.markdown("</div></div>", unsafe_allow_html=True)

    if submit_tot:
        if modo_total == "Totais do ranking (Top Nomes)":
            show_filters(Escopo=escopo_t, Localidade=localidade_label_t, Década=("Todas" if dec_t is None else dec_t), N=topn_t)
            df_m = get_ranking_unified(dec_t if dec_t else None, "M", localidade_t, topn_t)
            df_f = get_ranking_unified(dec_t if dec_t else None, "F", localidade_t, topn_t)
            tot_m = int(df_m["frequencia"].sum()) if not df_m.empty else 0
            tot_f = int(df_f["frequencia"].sum()) if not df_f.empty else 0
            total = tot_m + tot_f
            reg_m = len(df_m) if not df_m.empty else 0
            reg_f = len(df_f) if not df_f.empty else 0
            reg_total = reg_m + reg_f

            kc1, kc2, kc3 = st.columns([1,1,1])
            with kc1:
                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.markdown(f'<div class="kpi">{tot_m:,}</div>'.replace(",", "."), unsafe_allow_html=True)
                st.markdown('<div class="kpi-sub">Masculino (soma do Top Nomes)</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)
            with kc2:
                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.markdown(f'<div class="kpi">{tot_f:,}</div>'.replace(",", "."), unsafe_allow_html=True)
                st.markdown('<div class="kpi-sub">Feminino (soma do Top Nomes)</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)
            with kc3:
                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.markdown(f'<div class="kpi">{total:,}</div>'.replace(",", "."), unsafe_allow_html=True)
                st.markdown('<div class="kpi-sub">Total (M + F)</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            st.caption(f"Registros retornados — M: {reg_m} • F: {reg_f} • Total: {reg_total}")

            share_m = (tot_m/total*100.0) if total else 0.0
            share_f = (tot_f/total*100.0) if total else 0.0
            st.caption(f"Participação: Masculino {share_m:.1f}% • Feminino {share_f:.1f}%")
            bars = pd.DataFrame({"sexo": ["Masculino","Feminino"], "total": [tot_m, tot_f]})
            ch = alt.Chart(bars).mark_bar().encode(
                x=alt.X("total:Q", title="Total (soma do Top Nomes)", axis=alt.Axis(format="~s")),
                y=alt.Y("sexo:N", sort=None, title="Sexo"),
                tooltip=["sexo", "total"],
            ).properties(height=160)
            st.altair_chart(ch, use_container_width=True)

            if escopo_t == "Brasil":
                res = get_populacao_brasil()
                if res["ok"]:
                    cobertura = total / res["pop"]
                    st.caption(f"Cobertura aproximada do Top Nomes sobre a população do Brasil: {cobertura:.1%}.")
                else:
                    st.caption("Não foi possível obter a projeção de população do Brasil agora.")
        else:  # Projeção Brasil
            show_filters(Escopo=escopo_t, Localidade=localidade_label_t, Fonte="Projeções de População IBGE")
            if escopo_t != "Brasil":
                st.warning("A API pública de projeções só traz Brasil. Selecione Brasil no escopo.")
            else:
                res = get_populacao_brasil()
                if res["ok"]:
                    k1, k2 = st.columns([2,3])
                    with k1:
                        st.markdown('<div class="card">', unsafe_allow_html=True)
                        st.markdown(f'<div class="kpi">{res["pop"]:,}</div>'.replace(",", "."), unsafe_allow_html=True)
                        st.markdown('<div class="kpi-sub">População total (projeção)</div>', unsafe_allow_html=True)
                        st.markdown('</div>', unsafe_allow_html=True)
                    with k2:
                        st.info("A projeção pública não é desagregada por sexo/UF/município. Use o modo 'Totais do ranking (Top Nomes)' para essas comparações.")
                else:
                    st.error("Não foi possível obter a projeção de população do IBGE.")
                    with st.expander("Detalhes do erro"):
                        st.code(res["err"])

# ---------- Evolução global ----------
with tab_global:
    st.subheader("📊 Evolução global")
    estados = get_estados()
    sub1, sub2 = st.tabs(["🌍 Global (A→B)", "🕰️ Por década (Δ vs anterior)"])

    with sub1:
        with st.form("form_global_ab"):
            st.markdown('<div class="card">', unsafe_allow_html=True)
            cTop, cMode = st.columns([2,2])
            with cTop:
                only_prev = st.checkbox("Comparar com década anterior (B vs B-10)", value=False)
            with cMode:
                set_mode_g = st.selectbox("Conjunto de nomes",
                                          ["Top-N de A & B (interseção)", "Top-N só de B", "Top-N só de A"], index=0)
            c1, c2, c3 = st.columns(3)
            with c2:
                dec_b_g = st.selectbox("Década B", [1940,1950,1960,1970,1980,1990,2000,2010], index=7)
            if only_prev:
                dec_a_g = dec_b_g - 10
                st.caption(f"Década A: {dec_a_g}")
            else:
                with c1:
                    dec_a_g = st.selectbox("Década A", [1930,1940,1950,1960,1970,1980,1990,2000], index=6)
            with c3:
                sexo_g = st.selectbox("Sexo", ["Todos","M","F"], index=0)
            c4, c5 = st.columns(2)
            with c4:
                escopo_g = st.selectbox("Escopo", ["Brasil","UF","Município"], index=0)
            with c5:
                top_g = st.slider("Top Nomes (N)", 20, 200, 100, 10)
            localidade_g = "BR"; localidade_label_g = "Brasil"
            if escopo_g == "UF":
                uf_g = st.selectbox("UF", estados["sigla"].tolist(), index=0)
                localidade_g = str(int(estados.loc[estados["sigla"] == uf_g, "id"].iloc[0]))
                localidade_label_g = uf_g
            elif escopo_g == "Município":
                uf_g2 = st.selectbox("UF do município", estados["sigla"].tolist(), index=0)
                mdf_g = get_municipios(uf_g2)
                if mdf_g.empty:
                    st.warning("Não foi possível carregar municípios desta UF agora."); st.stop()
                mun_g = st.selectbox("Município", mdf_g["municipio"].tolist(), index=0)
                localidade_g = str(int(mdf_g.loc[mdf_g["municipio"] == mun_g, "id_municipio"].iloc[0]))
                localidade_label_g = f"{mun_g}/{uf_g2}"
            st.markdown('<div class="right">', unsafe_allow_html=True)
            submit_glob = st.form_submit_button("Gerar análise")
            st.markdown('</div></div>', unsafe_allow_html=True)

        if submit_glob:
            show_filters(Décadas=f"{dec_a_g} → {dec_b_g}", Sexo=sexo_g, Escopo=escopo_g, Localidade=localidade_label_g, N=top_g, Conjunto=set_mode_g)
            sx = None if sexo_g == "Todos" else sexo_g
            set_key = {"Top-N de A & B (interseção)":"intersect","Top-N só de B":"only_B","Top-N só de A":"only_A"}[set_mode_g]
            base = growth_between_decades(dec_a_g, dec_b_g, sx, localidade_g, topn=int(top_g), set_mode=set_key)
            if base.empty:
                st.warning("Sem dados cruzáveis.")
            else:
                up = base.sort_values("delta", ascending=False).head(20)
                dn = base.sort_values("delta", ascending=True).head(20)
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Top crescimentos (Δ A→B)**")
                    st.dataframe(up[["nome","freq_a","freq_b","delta","pct","delta_rank"]], use_container_width=True, hide_index=True)
                with c2:
                    st.markdown("**Top quedas (Δ A→B)**")
                    st.dataframe(dn[["nome","freq_a","freq_b","delta","pct","delta_rank"]], use_container_width=True, hide_index=True)

    with sub2:
        with st.form("form_global_dec"):
            st.markdown('<div class="card">', unsafe_allow_html=True)
            c1, c2, c3 = st.columns(3)
            with c1:
                dec_ref = st.selectbox("Década de referência", [1940,1950,1960,1970,1980,1990,2000,2010], index=6)
            with c2:
                sexo_h = st.selectbox("Sexo", ["Todos","M","F"], index=0)
            with c3:
                top_h = st.slider("Top Nomes (N)", 20, 200, 100, 10)
            c4, c5 = st.columns(2)
            with c4:
                escopo_h = st.selectbox("Escopo", ["Brasil","UF","Município"], index=0)
            with c5:
                filtro_nome = st.text_input("Buscar nome (ex.: enzo)", "enzo")
            localidade_h = "BR"; localidade_label_h = "Brasil"
            if escopo_h == "UF":
                uf_h = st.selectbox("UF", estados["sigla"].tolist(), index=0)
                localidade_h = str(int(estados.loc[estados["sigla"] == uf_h, "id"].iloc[0]))
                localidade_label_h = uf_h
            elif escopo_h == "Município":
                uf_h2 = st.selectbox("UF do município", estados["sigla"].tolist(), index=0)
                mdf_h = get_municipios(uf_h2)
                if mdf_h.empty:
                    st.warning("Não foi possível carregar municípios desta UF agora."); st.stop()
                mun_h = st.selectbox("Município", mdf_h["municipio"].tolist(), index=0)
                localidade_h = str(int(mdf_h.loc[mdf_h["municipio"] == mun_h, "id_municipio"].iloc[0]))
                localidade_label_h = f"{mun_h}/{uf_h2}"
            st.markdown('<div class="right">', unsafe_allow_html=True)
            submit_dec = st.form_submit_button("Gerar evolução da década")
            st.markdown('</div></div>', unsafe_allow_html=True)

        if submit_dec:
            dec_prev = dec_ref - 10
            show_filters(Comparação=f"{dec_prev} → {dec_ref}", Sexo=sexo_h, Escopo=escopo_h, Localidade=localidade_label_h, N=top_h)
            sx = None if sexo_h == "Todos" else sexo_h
            base = growth_between_decades(dec_prev, dec_ref, sx, localidade_h, topn=int(top_h), set_mode="intersect")
            if base.empty:
                st.warning("Sem dados cruzáveis.")
            else:
                if filtro_nome:
                    destaque = base[base["nome"].str.contains(filtro_nome, case=False, na=False)]
                    if not destaque.empty:
                        st.success(f"Destaques contendo '{filtro_nome}':")
                        st.dataframe(destaque, use_container_width=True, hide_index=True)
                up = base.sort_values("delta", ascending=False).head(20)
                dn = base.sort_values("delta", ascending=True).head(20)
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Top crescimentos (Δ vs década anterior)**")
                    st.dataframe(up[["nome","freq_a","freq_b","delta","pct","delta_rank"]],
                                 use_container_width=True, hide_index=True)
                with c2:
                    st.markdown("**Top quedas (Δ vs década anterior)**")
                    st.dataframe(dn[["nome","freq_a","freq_b","delta","pct","delta_rank"]],
                                 use_container_width=True, hide_index=True)

# ---------- População BR ----------
with tab_pop:
    st.subheader("Projeção de População — Brasil (IBGE)")
    res = get_populacao_brasil()
    if res["ok"]:
        pop_br = res["pop"]
        st.success("Projeção carregada com sucesso.")
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown(f'<div class="kpi">{pop_br:,}</div>'.replace(",", "."), unsafe_allow_html=True)
        st.markdown('<div class="kpi-sub">População total (projeção)</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        st.caption("A API pública de projeções não disponibiliza desagregação por sexo/UF/município.")
    else:
        st.error("Não foi possível obter a projeção de população do IBGE.")
        with st.expander("Detalhes do erro"):
            st.code(res["err"])
