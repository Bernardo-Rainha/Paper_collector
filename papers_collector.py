
"""
FONTES (rodam juntas):
  1. arXiv API
  
  2. Semantic Scholar API — requer respeitar 1 req/s .
     Coloque sua chave na variável S2_API_KEY abaixo
     # Chave gratuita em https://www.semanticscholar.org/product/api para contas estudantis

  3. NASA NTRS (https://ntrs.nasa.gov/api)

COMANDOS:
  python papers_collector.py             # coleta normal
  python papers_collector.py --dry-run   # só lista
  python papers_collector.py --test-s2   # testa a chave do S2 (1 requisição)
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# ============================ CONFIGURAÇÕES ============================
KEYWORDS = [
    "software engineering", "microservices", "embedded systems",
    "computer architecture" "Information Retrieval", "devops", "machine learning",
    "internet of things", "cloud computing", "ci/cd",
]

                              # FONTE 1: arXive (padrão)
CATEGORIES = ["cs.SE", "cs.AR", "cs.IR", "cs.DC", "cs.ET", "cs.CE", "cs.SD", "cs.AI"]

DAYS_BACK = 10
MAX_RESULTS = 5
OUTPUT_DIR = "_BIBLIOTECA"
DOWNLOAD_PDF = True

USE_SEMANTIC_SCHOLAR = True
S2_MAX_RESULTS = 5
S2_MAX_RETRIES = 2
S2_PACING = 1.3               # segundos ENTRE requisições S2 (limite oficial: 1 req/s)

USE_NTRS = True               # fonte 3: NASA Technical Reports Server
NTRS_MAX_RESULTS = 5          
NTRS_PACING = 1.0             

# >>> COLE SUA CHAVE AQUI (entre aspas) <<<
S2_API_KEY = ""
# ======================================================================

ARXIV_API = "https://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
NTRS_API = "https://ntrs.nasa.gov/api"
SEEN_FILE = os.path.join(OUTPUT_DIR, "vistos.json")
UA = {"User-Agent": "papers-collector/2.3 (uso pessoal; estudo)"}


# Estado (deduplicação)
def carregar_vistos():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return set(data.get("ids", [])), set(data.get("titulos", []))
        return set(data), set()
    return set(), set()


def salvar_vistos(ids, titulos):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump({"ids": sorted(ids), "titulos": sorted(titulos)},
                  f, ensure_ascii=False, indent=2)


def norm_titulo(t):
    return re.sub(r"\W+", " ", t.lower()).strip()


# Resumo automático
def resumo_extrativo(texto, n=3):
    sentencas = [s.strip() for s in re.split(r"(?<=[.!?])\s+", texto) if s.strip()]
    if len(sentencas) <= n:
        return texto
    freq = {}
    for w in re.findall(r"\b[a-zA-Z]{4,}\b", texto.lower()):
        freq[w] = freq.get(w, 0) + 1
    pontuadas = []
    for i, s in enumerate(sentencas):
        palavras = re.findall(r"\b[a-zA-Z]{4,}\b", s.lower())
        score = sum(freq.get(w, 0) for w in palavras) / max(len(palavras), 1)
        pontuadas.append((score, i, s))
    top = sorted(pontuadas, reverse=True)[:n]
    top.sort(key=lambda x: x[1])
    return " ".join(s for _, _, s in top)


def gerar_resumo(paper):
    if paper.get("tldr"):
        return paper["tldr"]
    if paper.get("resumo"):
        return resumo_extrativo(paper["resumo"])
    return "(sem abstract disponível)"



# Fonte 1: arXiv
def montar_query_arxiv():
    cats = " OR ".join(f"cat:{c}" for c in CATEGORIES)
    kws = " OR ".join(f'all:"{k}"' for k in KEYWORDS)
    return f"({cats}) AND ({kws})"


def buscar_arxiv(query, max_results, max_retries=3):
    params = urllib.parse.urlencode({
        "search_query": query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "start": 0,
        "max_results": max_results,
    })
    req = urllib.request.Request(f"{ARXIV_API}?{params}", headers=UA)
    for tentativa in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return ET.fromstring(resp.read())
        except Exception as e:
            if tentativa == max_retries:
                raise
            espera = 5 * tentativa      # 5s, 10s
            print(f"    arXiv não respondeu (tentativa {tentativa}/"
                  f"{max_retries}): {type(e).__name__}. Aguardando {espera}s...")
            time.sleep(espera)


def parse_arxiv(root, data_corte):
    ns = {"a": "http://www.w3.org/2005/Atom"}
    papers = []
    for entry in root.findall("a:entry", ns):
        arxiv_id = entry.findtext("a:id", "", ns).rsplit("/", 1)[-1]
        published = entry.findtext("a:published", "", ns)[:10]
        if published < data_corte:
            continue
        authors = [a.findtext("a:name", "", ns)
                   for a in entry.findall("a:author", ns)]
        pdf = next((l.get("href") for l in entry.findall("a:link", ns)
                    if l.get("title") == "pdf"), None)
        papers.append({
            "id": "arxiv:" + arxiv_id,
            "titulo": " ".join(entry.findtext("a:title", "", ns).split()),
            "resumo": " ".join(entry.findtext("a:summary", "", ns).split()),
            "tldr": None,
            "autores": authors,
            "publicado": published,
            "url": entry.findtext("a:id", "", ns),
            "pdf": pdf,
            "categorias": [c.get("term") for c in entry.findall("a:category", ns)],
            "fonte": "arXiv",
        })
    return papers


# Fonte 2: Semantic Scholar (1 req/s cumulativo!)
def _s2_headers():
    h = dict(UA)
    if S2_API_KEY:
        h["x-api-key"] = S2_API_KEY
    return h


def s2_request(params, max_retries=S2_MAX_RETRIES):
    """NÃO ADIANTA AUMENTAR AS REQUESTS, o Semantic Scholar só deixa 1/s."""

    url = S2_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_s2_headers())
    tentativa = 0
    while True:
        time.sleep(S2_PACING)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                rate = {k: resp.headers.get(k) for k in (
                    "x-ratelimit-limit", "x-ratelimit-remaining",
                    "x-ratelimit-reset")}
                return json.loads(resp.read()), rate, None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                tentativa += 1
                if tentativa > max_retries:
                    return None, None, ("rate limit persistente após "
                                        f"{max_retries} tentativas")
                retry_after = e.headers.get("Retry-After", "")
                espera = int(retry_after) if retry_after.isdigit() else 15 * tentativa
                print(f"    429 no S2 (tentativa {tentativa}/{max_retries}), "
                      f"aguardando {espera}s conforme Retry-After...")
                time.sleep(espera)
                continue
            return None, None, f"HTTP {e.code}"
        except Exception as e:
            return None, None, f"erro de rede: {e}"


# Diagnóstico da chave do Semantic Scholar
def testar_s2():
    print("Testando Semantic Scholar com 1 requisição...")
    print(f"  chave configurada: {'SIM (' + S2_API_KEY[:8] + '...)' if S2_API_KEY else 'NÃO'}")
    params = {"query": "computer science", "limit": 1,
              "fields": "title,year,publicationDate"}

    url = S2_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_s2_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            print(f"  ✓ SUCESSO — {data.get('total', 0)} papers no índice")
            for k in ("x-ratelimit-limit", "x-ratelimit-remaining",
                      "x-ratelimit-reset"):
                v = resp.headers.get(k)
                if v is not None:
                    print(f"  {k}: {v}")
            return True
    except urllib.error.HTTPError as e:
        print(f"  ✗ HTTP {e.code}")
        print("  --- headers da resposta ---")
        for k, v in e.headers.items():
            print(f"    {k}: {v}")
        print("  --- corpo do erro (primeiros 300 chars) ---")
        try:
            print("   ", e.read()[:300].decode("utf-8", errors="replace"))
        except Exception:
            pass
        print("  → Com esses dados dá pra saber se a cota acabou")
        print("    (x-ratelimit-remaining: 0) ou se a chave foi rejeitada.")
        return False
    except Exception as e:
        print(f"  ✗ erro de rede: {e}")
        return False
    total = data.get("total", 0)
    print(f"  ✓ SUCESSO — {total} papers no índice para 'computer science'")
    if rate.get("x-ratelimit-remaining") is not None:
        print(f"  limite: {rate['x-ratelimit-limit']} | "
              f"restantes: {rate['x-ratelimit-remaining']} | "
              f"reset: {rate['x-ratelimit-reset']}")
    else:
        print("  (headers de rate limit ausentes — normal em algumas contas)")
    return True


def buscar_semantic_scholar(data_corte, max_total, limite_por_kw=20):
    papers, vistos_local = [], set()
    ano_atual = str(datetime.now().year)
    campos = ("title,abstract,authors,year,publicationDate,url,"
              "externalIds,openAccessPdf,tldr,citationCount")
    primeira = True

    for kw in KEYWORDS:
        if len(papers) >= max_total:
            break
        offset = 0
        while offset < limite_por_kw and len(papers) < max_total:
            params = {"query": kw, "fields": campos, "year": ano_atual,
                      "limit": 20, "offset": offset,
                      "sort": "publicationDate:desc"}
            data, rate, erro = s2_request(params)
            if erro:
                if "rate limit" in erro:
                    print(f"    ! {erro}. Pulando S2 nesta execução.")
                    if S2_API_KEY:
                        print("      Chave está configurada, mas o 429 "
                              "persistiu.")
                        print("      Rode: python papers_collector.py --test-s2")
                        print("      Se falhar, a chave pode estar errada ou "
                              "com espaços extras.")
                    else:
                        print("      SEM chave configurada — o pool anônimo "
                              "está esgotado.")
                        print("      Obtenha uma gratuita em "
                              "https://www.semanticscholar.org/product/api")
                    return papers
                print(f"    ! S2 erro para '{kw}': {erro}", file=sys.stderr)
                break
            if primeira and rate.get("x-ratelimit-remaining") is not None:
                print(f"    cota S2 restante: {rate['x-ratelimit-remaining']}")
                primeira = False

            lote = data.get("data", [])
            if not lote:
                break
            for p in lote:
                pub = p.get("publicationDate")
                if pub and pub < data_corte:
                    offset = limite_por_kw
                    break
                pid = p.get("paperId") or norm_titulo(p.get("title", ""))
                if not p.get("title") or pid in vistos_local:
                    continue
                vistos_local.add(pid)
                papers.append({
                    "id": "s2:" + pid,
                    "titulo": p["title"],
                    "resumo": p.get("abstract") or "",
                    "tldr": (p.get("tldr") or {}).get("text"),
                    "autores": [a.get("name", "") for a in p.get("authors", [])],
                    "publicado": pub or f"{p.get('year', '')}-01-01",
                    "url": p.get("url", ""),
                    "pdf": (p.get("openAccessPdf") or {}).get("url"),
                    "citacoes": p.get("citationCount", 0),
                    "categorias": [],
                    "fonte": "Semantic Scholar",
                })
            if len(lote) < 20 or offset == limite_por_kw:
                break
            offset += 20
    return papers[:max_total]


# Fonte 3: NASA NTRS (sem chave, sem limite rígido)
def ntrs_get_search(kw, data_corte, size=20):
    """A filtragem de data é feita no cliente."""
    params = urllib.parse.urlencode({
        "q": kw,
        "page.size": size,
        "page.from": 0,
        "sort.field": "published",
        "sort.order": "desc",
    })
    url = f"{NTRS_API}/citations/search?{params}"
    tentativa = 0
    while True:
        time.sleep(NTRS_PACING)
        req = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            tentativa += 1
            if tentativa > 3:
                print(f"    ! NTRS HTTP {e.code} persistente para '{kw}'",
                      file=sys.stderr)
                return {}
            print(f"    NTRS HTTP {e.code} (tentativa {tentativa}/3), "
                  f"aguardando {5 * tentativa}s...")
            time.sleep(5 * tentativa)
        except Exception as e:
            print(f"    ! NTRS erro de rede para '{kw}': {e}", file=sys.stderr)
            return {}


def ntrs_buscar_pdf(citation_id):
    try:
        time.sleep(NTRS_PACING)
        req = urllib.request.Request(f"{NTRS_API}/citations/{citation_id}",
                                     headers=UA)
        with urllib.request.urlopen(req, timeout=30) as resp:
            det = json.loads(resp.read())
        for d in det.get("downloads", []):
            pdf = (d.get("links") or {}).get("pdf")
            if pdf:

                #relativo pra NASA
                return urllib.parse.urljoin("https://ntrs.nasa.gov", pdf)
    except Exception:
        pass
    return None


def buscar_ntrs(data_corte, max_total):
    papers, vistos_local = [], set()
    for kw in KEYWORDS:
        if len(papers) >= max_total:
            break
        data = ntrs_get_search(kw, data_corte)
        lote = data.get("results") or data.get("data") or []
        for p in lote:
            pub = (p.get("publicationDate") or "")[:10]
            if pub and pub < data_corte:
                break                        # ordenado desc: resto é antigo
            cid = str(p.get("id", ""))
            if not cid or cid in vistos_local or not p.get("title"):
                continue
            vistos_local.add(cid)
            autores = [a.get("name", "") if isinstance(a, dict) else str(a)
                       for a in p.get("authors", [])]
            papers.append({
                "id": "ntrs:" + cid,
                "titulo": " ".join(p["title"].split()),
                "resumo": " ".join((p.get("abstract") or "").split()),
                "tldr": None,
                "autores": autores,
                "publicado": pub or "????-??-??",
                "url": f"https://ntrs.nasa.gov/citations/{cid}",
                "pdf": ntrs_buscar_pdf(cid) if p.get("downloadsAvailable") else None,
                "citacoes": 0,
                "categorias": (p.get("subjectCategories")
                               or p.get("keywords", []))[:5],
                "fonte": "NASA NTRS",
            })
    return papers[:max_total]


# Download e relatório
def baixar_pdf(url, destino):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as resp, open(destino, "wb") as f:
            f.write(resp.read())
        return True
    except Exception as e:
        print(f"    ! falha no PDF: {e}", file=sys.stderr)
        return False


def nome_arquivo_seguro(titulo, max_len=80):
    nome = re.sub(r'[\\/*?:"<>|]', "", titulo)
    return "_".join(nome.split())[:max_len]


def gerar_relatorio(pasta, papers):
    data = os.path.basename(pasta)
    linhas = [f"# 📚 Artigos novos — {data} ({len(papers)} papers)\n"]
    for i, p in enumerate(papers, 1):
        linhas.append(f"## {i}. {p['titulo']}")
        autores = ", ".join(p["autores"][:5])
        if len(p["autores"]) > 5:
            autores += " et al."
        linhas.append(f"**Autores:** {autores}  ")
        linhas.append(f"**Publicado:** {p['publicado']} | **Fonte:** {p['fonte']}"
                      + (f" | **Citações:** {p.get('citacoes', 0)}" if p.get("citacoes") else "") + "  ")
        linhas.append(f"**Link:** {p['url']}\n")
        linhas.append(f"**Resumo automático:** {p['resumo_auto']}\n")
        if p["categorias"]:
            linhas.append(f"*Categorias: {', '.join(p['categorias'])}*\n")
        linhas.append("---\n")
    with open(os.path.join(pasta, f"_RELATORIO_{data}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))


# Markdown
def _yaml_lista(itens):
    return "[" + ", ".join(str(i) for i in itens) + "]"


def salvar_nota_obsidian(pasta, p, base):
    """Gera um .md com frontmatter YAML"""

    tags = ["artigos", p["fonte"].lower().replace(" ", "-")]
    tags += [c.lower() for c in p.get("categorias", [])]
    titulo = p["titulo"].replace('"', "'")
    autores = _yaml_lista(p["autores"])
    cats = _yaml_lista(p.get("categorias", []))
    tags_yaml = _yaml_lista(tags)
    pdf_link = f"[[{p['arquivo_pdf']}]]" if p.get("arquivo_pdf") else "(não baixado)"

    nota = f"""---
tipo: artigo
titulo: "{titulo}"
autores: {autores}
publicado: {p['publicado']}
fonte: {p['fonte']}
citacoes: {p.get('citacoes', 0)}
categorias: {cats}
tags: {tags_yaml}
link: {p['url']}
---

# {p['titulo']}

**Publicado:** {p['publicado']} | **Fonte:** {p['fonte']}
**PDF:** {pdf_link}

## Resumo automático
{p['resumo_auto']}

## Abstract original
{p['resumo'] if p.get('resumo') else '(indisponível)'}

---
*Coletado em {datetime.now().strftime('%Y-%m-%d')} por papers_collector.py*
"""
    with open(os.path.join(pasta, base + ".md"), "w", encoding="utf-8") as f:
        f.write(nota)


def buscar_colecao(termo):
    termo = termo.lower()
    resultados = []
    for raiz, _dirs, arquivos in os.walk(OUTPUT_DIR):
        for fn in arquivos:
            if not fn.endswith(".json") or fn == "vistos.json":
                continue
            try:
                with open(os.path.join(raiz, fn), "r", encoding="utf-8") as f:
                    p = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            texto = " ".join([p.get("titulo", ""), p.get("resumo", ""),
                              p.get("resumo_auto", ""),
                              " ".join(p.get("autores", []))]).lower()
            if termo in texto:
                resultados.append((p, raiz, fn))
    return resultados


def main():
    ap = argparse.ArgumentParser(description="Coletor de artigos (arXiv + Semantic Scholar)")
    ap.add_argument("--dry-run", action="store_true", help="só lista, não salva")
    ap.add_argument("--test-s2", action="store_true", help="testa a chave do S2 e sai")
    ap.add_argument("--busca", metavar="TERMO", help="busca na coleção local e sai")
    args = ap.parse_args()

    if args.test_s2:
        ok = testar_s2()
        sys.exit(0 if ok else 1)

    if args.busca:
        resultados = buscar_colecao(args.busca)
        print(f"{len(resultados)} paper(s) encontrados para '{args.busca}':\n")
        for p, raiz, fn in resultados:
            print(f"■ {p['titulo']}")
            print(f"  {p['publicado']} | {p['fonte']} | {raiz}")
            print(f"  Resumo: {(p.get('resumo_auto') or '')[:150]}...")
            if p.get("arquivo_pdf"):
                print(f"  PDF: {os.path.join(raiz, p['arquivo_pdf'])}")
            print()
        sys.exit(0)

    data_corte = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
    vistos_ids, vistos_titulos = carregar_vistos()
    print(f"Janela de busca: artigos desde {data_corte}\n")

    papers_arxiv = []
    print("▶ Consultando arXiv...")
    try:
        root = buscar_arxiv(montar_query_arxiv(), MAX_RESULTS)
        papers_arxiv = parse_arxiv(root, data_corte)
        print(f"  {len(papers_arxiv)} papers na janela")
    except Exception as e:
        print(f"  ! falha no arXiv: {e}", file=sys.stderr)
        print("  → seguindo com as demais fontes")

    papers_s2 = []
    if USE_SEMANTIC_SCHOLAR:
        print("▶ Consultando Semantic Scholar...")
        papers_s2 = buscar_semantic_scholar(data_corte, S2_MAX_RESULTS)
        print(f"  {len(papers_s2)} papers na janela")

    papers_ntrs = []
    if USE_NTRS:
        print("▶ Consultando NASA NTRS...")
        try:
            papers_ntrs = buscar_ntrs(data_corte, NTRS_MAX_RESULTS)
            print(f"  {len(papers_ntrs)} papers na janela")
        except Exception as e:
            print(f"  ! falha no NTRS: {e}", file=sys.stderr)

    todos = papers_arxiv + papers_s2 + papers_ntrs
    novos, vistos_agora = [], set()
    for p in todos:
        chave_t = norm_titulo(p["titulo"])
        if p["id"] in vistos_ids or chave_t in vistos_titulos or chave_t in vistos_agora:
            continue
        vistos_agora.add(chave_t)
        p["resumo_auto"] = gerar_resumo(p)
        novos.append(p)

    print(f"\n{len(todos)} no total | {len(novos)} novos\n")

    if args.dry_run:
        for p in novos:
            print(f"[{p['publicado']}] ({p['fonte']}) {p['titulo']}")
            print(f"    Resumo: {p['resumo_auto'][:200]}...\n")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pasta_data = os.path.join(OUTPUT_DIR, datetime.now().strftime("%Y-%m-%d"))
    os.makedirs(pasta_data, exist_ok=True)

    index = []
    for p in novos:
        print(f"✔ ({p['fonte']}) {p['titulo'][:80]}")
        base = nome_arquivo_seguro(p["titulo"])
        if DOWNLOAD_PDF and p["pdf"]:
            if baixar_pdf(p["pdf"], os.path.join(pasta_data, base + ".pdf")):
                p["arquivo_pdf"] = base + ".pdf"
            time.sleep(1)
        with open(os.path.join(pasta_data, base + ".json"), "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)
        salvar_nota_obsidian(pasta_data, p, base)
        index.append(p)
        vistos_ids.add(p["id"])
        vistos_titulos.add(norm_titulo(p["titulo"]))

    if index:
        with open(os.path.join(pasta_data, "index.json"), "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        gerar_relatorio(pasta_data, index)

    salvar_vistos(vistos_ids, vistos_titulos)
    print(f"\nConcluído: {len(index)} artigos salvos em '{pasta_data}'")
    if index:
        print(f"Relatório: {pasta_data}/_RELATORIO_{os.path.basename(pasta_data)}.md")


if __name__ == "__main__":
    main()
