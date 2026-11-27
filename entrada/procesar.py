"""Entrada de contenido por Telegram para @jonathanrod.ia (corre en GitHub Actions, sin el Mac).

Jonathan le manda un video al bot de entrada. Si hay un reel esperando su intro (entrada/pendientes.json),
este script lo baja, corta el silencio del inicio y del final, le pone el titular y los subtítulos en la
línea gráfica (papel, tinta, tomate), lo pega al inicio del reel y deja el resultado en programadas.json
para que la rutina de la nube lo publique: a la hora que ya tenía o, si esa hora ya pasó, apenas quede listo.
Le avisa por el mismo bot cuando lo recibe, cuando queda listo y si algo falla.

Variables: TELEGRAM_ENTRADA_TOKEN y TELEGRAM_CHAT_ID (secretos del repo). Nunca se imprimen.
Modo prueba: PRUEBA_VIDEO=<ruta de un video> monta contra el primer pendiente y deja el resultado en
$RUNNER_TEMP/entrada/salida.mp4 sin Telegram, sin tocar el repo y sin publicar nada.
"""
import hashlib, json, os, re, shutil, subprocess, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


REPO = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
AQUI = Path(__file__).resolve().parent
TMP = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "entrada"
BASE = "https://jpaulrodriguez.github.io/ig-medios/"
BOG = ZoneInfo("America/Bogota")
TOKEN = os.environ.get("TELEGRAM_ENTRADA_TOKEN", "")
CHAT = str(os.environ.get("TELEGRAM_CHAT_ID", ""))
PRUEBA = os.environ.get("PRUEBA_VIDEO", "")
W, H, FPS = 1080, 1920, 30
PAPEL, TINTA, TOMATE = (243, 239, 230), (27, 27, 25), (228, 87, 46)
LIMITE_TG = 20 * 1024 * 1024
TITULAR_HASTA = 4.5
DEBILES = {"de", "del", "a", "al", "en", "que", "y", "o", "la", "el", "los", "las", "un", "una", "con", "por",
           "para", "mi", "tu", "su", "lo", "le", "les", "se", "me", "te", "no", "es", "muy", "más", "pero", "pues"}


# ---------- utilidades ----------

def limpio(texto):
    """Quita la llave de cualquier texto que vaya a imprimirse."""
    return str(texto).replace(TOKEN, "***") if TOKEN else str(texto)


def correr(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(limpio(f"{cmd[0]} falló: {r.stderr[-1500:]}"))
    return r.stdout


def tg(metodo, datos=None):
    url = f"https://api.telegram.org/bot{TOKEN}/{metodo}"
    try:
        with urllib.request.urlopen(url, urllib.parse.urlencode(datos or {}).encode(), timeout=60) as r:
            return json.load(r)
    except Exception as e:
        raise RuntimeError(limpio(f"Telegram {metodo}: {e}")) from None


def avisar(texto):
    if PRUEBA or not TOKEN:
        print("[aviso]", texto)
        return
    try:
        tg("sendMessage", {"chat_id": CHAT, "text": texto, "parse_mode": "HTML", "disable_web_page_preview": "true"})
    except Exception as e:
        print("no se pudo avisar:", limpio(e))


def descargar(url, destino):
    destino.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as r, open(destino, "wb") as f:
        shutil.copyfileobj(r, f)
    return destino


def cargar(ruta, defecto):
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else defecto


def guardar(ruta, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ---------- texto en pantalla ----------

def fuente(n, peso):
    from PIL import ImageFont
    f = ImageFont.truetype(str(AQUI / "fuentes" / "NunitoSans-var.ttf"), n)
    f.set_variation_by_axes([peso, 100, 12, 500])
    return f


def partir(txt, f, ancho, d, junto=None):
    """Una línea si cabe; si no, dos lo más parejas posible, sin palabra sola abajo y sin partir `junto`."""
    if d.textlength(txt, font=f) <= ancho:
        return [txt]
    ws, mejor = txt.split(), None
    if junto and junto in txt:
        ws = txt.replace(junto, junto.replace(" ", "\u00a0")).split(" ")
        ws = [w.replace("\u00a0", " ") for w in ws]
    for k in range(1, len(ws)):
        l1, l2 = " ".join(ws[:k]), " ".join(ws[k:])
        m = max(d.textlength(l1, font=f), d.textlength(l2, font=f))
        if m <= ancho and (mejor is None or m < mejor[0]):
            mejor = (m, [l1, l2])
    return mejor[1] if mejor else [txt]


def caja(d, lineas, f, y, resaltar=None):
    alto_l = int(f.size * 1.12)
    anchos = [d.textlength(l, font=f) for l in lineas]
    bw, bh = max(anchos) + 68, alto_l * len(lineas) + 44
    x0 = (W - bw) / 2
    d.rounded_rectangle([x0, y, x0 + bw, y + bh], radius=22, fill=PAPEL + (238,))
    for k, l in enumerate(lineas):
        tx, ty = (W - anchos[k]) / 2, y + 22 + k * alto_l - f.size * 0.08
        if resaltar and resaltar in l:
            a, b = l.split(resaltar, 1)
            d.text((tx, ty), a, font=f, fill=TINTA)
            tx2 = tx + d.textlength(a, font=f)
            d.text((tx2, ty), resaltar, font=f, fill=TOMATE)
            d.text((tx2 + d.textlength(resaltar, font=f), ty), b, font=f, fill=TINTA)
        else:
            d.text((tx, ty), l, font=f, fill=TINTA)


def capa(ruta, titular=None, resaltar=None, sub=None):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if titular:
        f = fuente(66, 900)
        caja(d, partir(titular, f, 860, d, resaltar), f, 262, resaltar)
    if sub:
        f = fuente(56, 850)
        caja(d, partir(sub, f, 900, d), f, 1270)
    im.save(ruta)
    return ruta


# ---------- transcripción ----------

def palabras(wav):
    from faster_whisper import WhisperModel
    modelo = WhisperModel(os.environ.get("WHISPER_MODELO", "large-v3-turbo"), device="cpu", compute_type="int8")
    segs, _ = modelo.transcribe(str(wav), language="es", word_timestamps=True, vad_filter=True, beam_size=5)
    out = []
    for s in segs:
        for w in s.words or []:
            t = w.word.strip()
            if t:
                out.append((float(w.start), float(w.end), t))
    return out


def bloques(ws, ini, fin):
    """Agrupa palabras en subtítulos de hasta unos 30 caracteres, cortando en pausas y en puntuación."""
    grupos, actual = [], []
    for i, (a, b, t) in enumerate(ws):
        if actual:
            largo = len(" ".join(x[2] for x in actual) + " " + t)
            pausa = a - actual[-1][1]
            limite = 40 if re.search(r"[.,;:?!]$", t) else 30  # el final de una frase puede quedarse
            if pausa > 0.45 or largo > limite or re.search(r"[.,;:?!¿¡]$", actual[-1][2]):
                # un subtítulo no termina en «de», «que», «la»…: esas palabras pasan al siguiente
                arrastre = []
                while len(actual) > 1 and actual[-1][2].lower() in DEBILES and pausa <= 0.45:
                    arrastre.insert(0, actual.pop())
                grupos.append(actual)
                actual = arrastre
        actual.append((a, b, t))
    if actual:
        grupos.append(actual)
    subs = []
    for k, g in enumerate(grupos):
        a = max(0.0, g[0][0] - ini)
        b = (grupos[k + 1][0][0] - ini) if k + 1 < len(grupos) else (fin - ini)
        txt = re.sub(r"\s+", " ", " ".join(x[2] for x in g)).strip()
        txt = txt.rstrip(",;:") if not txt.endswith("...") else txt
        subs.append((round(a, 3), round(b, 3), txt))
    return subs


# ---------- montaje ----------

def sondear(ruta):
    return json.loads(correr(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(ruta)]))


RELLENOS = {"eh", "ehh", "ehm", "em", "emm", "mm", "mmm", "ah", "este", "o sea"}
ARRANQUES = {"bueno", "pues", "entonces", "listo", "okey", "ok", "hola", "ya"}
PAUSA_MAX = 0.45      # una pausa más larga se corta
ZOOM = 1.12           # plano cerrado
TRANSICION = 0.3      # fundido de la intro al reel


def _limpia(t):
    return re.sub(r"[^\wáéíóúüñ ]", "", t.lower()).strip()


def tramos(ws, dur):
    """Edita la intro: quita muletillas y el arranque de relleno, corta pausas largas y alterna plano abierto y
    cerrado en cada frase. Devuelve [(desde, hasta, zoom)] en tiempo original y las palabras en tiempo de salida."""
    quedan = []
    for i, w in enumerate(ws):
        t = _limpia(w[2])
        if t in RELLENOS or (not quedan and t in ARRANQUES):
            continue
        quedan.append((i, w))
    if not quedan:
        return [(0.0, dur, 1.0)], []
    # bloques de habla continua: se corta donde hay pausa larga o donde se quitó una muletilla
    bloques_, actual = [], [quedan[0]]
    for (i0, w0), (i1, w1) in zip(quedan, quedan[1:]):
        if w1[0] - w0[1] > PAUSA_MAX or i1 != i0 + 1:
            bloques_.append(actual)
            actual = []
        actual.append((i1, w1))
    bloques_.append(actual)
    piezas = []
    for k, bl in enumerate(bloques_):
        a = max(0.0, bl[0][1][0] - 0.12)
        b = min(dur, bl[-1][1][1] + (0.3 if k == len(bloques_) - 1 else 0.16))
        if piezas and a < piezas[-1][1]:
            a = piezas[-1][1]
        # dentro del bloque, un plano nuevo en cada fin de frase (si la frase dura más de 1,4 s)
        cortes = [a]
        for (_, w0), (_, w1) in zip(bl, bl[1:]):
            if re.search(r"[.?!]$", w0[2]) and w0[1] - cortes[-1] > 1.4:
                cortes.append((w0[1] + w1[0]) / 2)
        cortes.append(b)
        for x, y in zip(cortes, cortes[1:]):
            piezas.append([x, y])
    zooms, salida_ws, t_out, editadas = [], [], 0.0, []
    for n, (x, y) in enumerate(piezas):
        z = 1.0 if n % 2 == 0 else ZOOM
        editadas.append((round(x, 3), round(y, 3), z))
        for _, w in quedan:
            if x <= (w[0] + w[1]) / 2 < y:
                salida_ws.append((round(t_out + max(0.0, w[0] - x), 3), round(t_out + min(y, w[1]) - x, 3), w[2]))
        t_out += y - x
    return editadas, salida_ws


def montar(intro, base, pend, trabajo):
    info = sondear(intro)
    dur = float(info["format"]["duration"])
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    tiene_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    hdr = v.get("color_transfer") in ("arib-std-b67", "smpte2084")

    ws = []
    if tiene_audio:
        wav = trabajo / "voz.wav"
        correr(["ffmpeg", "-y", "-v", "error", "-i", str(intro), "-ac", "1", "-ar", "16000", str(wav)])
        ws = palabras(wav)
    piezas, ws_out = tramos(ws, dur) if ws else ([(0.0, dur, 1.0)], [])
    largo = sum(y - x for x, y, _ in piezas)
    subs = bloques(ws_out, 0.0, largo) if ws_out else []
    titular = pend.get("titular")
    hasta = min(TITULAR_HASTA, largo)

    # una capa por tramo entre cambios de subtítulo o de titular; nada encima durante el fundido final
    limite = round(largo - TRANSICION, 3)
    marcas = sorted({0.0, limite} | ({round(hasta, 3)} if titular else set())
                    | {a for a, _, _ in subs} | {b for _, b, _ in subs})
    marcas = [m for m in marcas if 0 <= m <= limite]
    capas = []
    for k, (a, b) in enumerate(zip(marcas, marcas[1:])):
        if b - a < 0.02:
            continue
        mid = (a + b) / 2
        sub = next((t for x, y, t in subs if x <= mid < y), None)
        con_tit = titular if (titular and mid < hasta) else None
        if sub or con_tit:
            capas.append((a, b, capa(trabajo / f"capa-{k:03d}.png", con_tit, pend.get("resaltar"), sub)))

    entradas = ["-i", str(intro), "-i", str(base)]
    for _, _, ruta in capas:
        entradas += ["-i", str(ruta)]
    tono = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
            "zscale=t=bt709:m=bt709:r=tv,format=yuv420p," if hdr else "")
    n = len(piezas)
    f = [f"[0:v]{tono}split={n}" + "".join(f"[s{k}]" for k in range(n))]
    if tiene_audio:
        f.append(f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit={n}" + "".join(f"[t{k}]" for k in range(n)))
    pares = []
    for k, (x, y, z) in enumerate(piezas):
        w2, h2 = int(W * z) // 2 * 2, int(H * z) // 2 * 2
        alto = "(ih-%d)*0.5" % H if z == 1.0 else "(ih-%d)*0.38" % H   # al acercar, el encuadre sube para no cortar la cabeza
        f.append(f"[s{k}]trim=start={x:.3f}:end={y:.3f},setpts=PTS-STARTPTS,scale={w2}:{h2}:force_original_aspect_ratio=increase,"
                 f"crop={W}:{H}:(iw-{W})/2:{alto},setsar=1,fps={FPS},format=yuv420p[v{k}]")
        d = y - x
        if tiene_audio:
            f.append(f"[t{k}]atrim=start={x:.3f}:end={y:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.02,"
                     f"afade=t=out:st={max(0.0, d - 0.03):.3f}:d=0.03[a{k}]")
        else:
            f.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={d:.3f}[a{k}]")
        pares.append(f"[v{k}][a{k}]")
    f.append("".join(pares) + f"concat=n={n}:v=1:a=1[i0][ia0]")
    f.append("[ia0]loudnorm=I=-13:TP=-1.5:LRA=11,aresample=48000[ia]")
    previo = "i0"
    for m_, (a, b, _) in enumerate(capas, start=2):
        f.append(f"[{previo}][{m_}:v]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'[i{m_}]")
        previo = f"i{m_}"
    f.append(f"[{previo}]fps={FPS},settb=1/{FPS}[iv]")
    f.append(f"[1:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},format=yuv420p,settb=1/{FPS}[bv]")
    f.append("[1:a]aformat=sample_rates=48000:channel_layouts=stereo[ba]")
    f.append(f"[iv][bv]xfade=transition=fade:duration={TRANSICION}:offset={largo - TRANSICION:.3f}[v]")
    f.append(f"[ia][ba]acrossfade=d={TRANSICION}[a]")
    salida = trabajo / "salida.mp4"
    correr(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex", ";".join(f), "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-maxrate", "12M", "-bufsize", "24M",
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", str(salida)])
    total = float(sondear(salida)["format"]["duration"])
    return salida, {"intro_s": round(largo, 1), "total_s": round(total, 1), "subtitulos": subs, "planos": piezas,
                    "texto": " ".join(t for _, _, t in ws_out), "original_s": round(dur, 1), "hdr": hdr}


# ---------- repo ----------

def git(*args):
    return correr(["git", *args], cwd=REPO)


def aplicar(cambio, mensaje):
    """Aplica el cambio sobre el main más reciente y empuja; si el Mac empujó en medio, vuelve a empezar."""
    for intento in range(4):
        git("fetch", "-q", "origin", "main")
        git("reset", "-q", "--hard", "origin/main")
        cambio()
        git("add", "-A")
        git("-c", "user.name=entrada-instagram", "-c", "user.email=entrada@localhost", "commit", "-q", "-m", mensaje)
        r = subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=REPO, capture_output=True, text=True)
        if r.returncode == 0:
            pedir_build()  # este empujón también dispara la rutina «publicar al recibir» de la nube
            return
        time.sleep(5 + intento * 5)
    raise RuntimeError("no pude empujar al repo después de cuatro intentos")


def pedir_build():
    """Los empujes hechos con el token de Actions pueden no disparar GitHub Pages: se lo pide a mano."""
    gh = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not gh or not repo:
        return
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/pages/builds", data=b"", method="POST",
                                 headers={"Authorization": f"Bearer {gh}", "Accept": "application/vnd.github+json"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:
        print("pages build:", getattr(e, "code", e))


def esperar_url(url, peso, maximo=420):
    inicio = time.time()
    while time.time() - inicio < maximo:
        try:
            req = urllib.request.Request(url + f"?v={int(time.time())}", method="HEAD")
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status == 200 and int(r.headers.get("Content-Length") or peso) == peso:
                    return True
        except Exception:
            pass
        time.sleep(10)
    return False


def hora_texto(dt):
    h = dt.strftime("%-I:%M")
    return f"{h} {'a. m.' if dt.hour < 12 else 'p. m.'}"


# ---------- flujo ----------

def elegir(pendientes, leyenda):
    for p in pendientes:
        if p["id"] in leyenda:
            return p
    return pendientes[0] if pendientes else None


ESTADO = {"pendientes": "entrada/pendientes.json", "montados": "entrada/montados.json",
          "listas": "entrada/listas.json", "registro": "entrada/registro.json"}


def ruta(clave):
    return REPO / ESTADO[clave]


def orden_de(texto):
    """«publica ya» o «en el horario programado». Sin orden explícita no se publica nada."""
    t = (texto or "").lower()
    for x, y in zip("áéíóú", "aeiou"):
        t = t.replace(x, y)
    if re.search(r"publica(lo)?\s+(ya|ahora)|ya mismo|de una|ahora mismo|sube(lo)?\s+ya", t):
        return "ya"
    if re.search(r"horario|programad|a su hora|a la hora", t):
        return "horario"
    return None


def cuando_texto(dt, ahora):
    dia = "hoy" if dt.date() == ahora.date() else ("mañana" if dt.date() == (ahora + timedelta(days=1)).date()
                                                  else f"el {dt.strftime('%d-%m')}")
    return f"{dia} a las {hora_texto(dt)}"


def a_programadas(piezas, ahora):
    """Mete las piezas en programadas.json (lo que la rutina de la nube publica cuando hay un empujón)."""
    prog = cargar(REPO / "programadas.json", {"zona": "America/Bogota", "ventana_min": 120, "piezas": []})
    ids = {x["id"] for x in piezas}
    prog["piezas"] = sorted([p for p in prog["piezas"] if p["id"] not in ids] + piezas,
                            key=lambda p: (p["fecha"], p["hora"]))
    prog["generado"] = ahora.strftime("%Y-%m-%d %H:%M") + " (entrada)"
    guardar(REPO / "programadas.json", prog)


def dar_orden(mont, orden, ahora):
    """Pasa un video montado a la lista de salida. Devuelve (cambio para aplicar, texto del aviso) o (None, aviso)."""
    piezas = json.loads(json.dumps(mont["piezas"]))
    reel = piezas[0]
    if orden == "ya":
        sale = ahora.replace(second=0, microsecond=0)
        for k, p in enumerate(piezas):
            t = sale + timedelta(minutes=5 * k)
            p["fecha"], p["hora"] = t.strftime("%Y-%m-%d"), t.strftime("%H:%M")
    else:
        sale = datetime.fromisoformat(f"{reel['fecha']}T{reel['hora']}").replace(tzinfo=BOG)
        if sale < ahora - timedelta(minutes=10):
            return None, (f"La hora programada de <b>{mont['nombre']}</b> ya pasó ({cuando_texto(sale, ahora)}). "
                          "Si quieres que salga, escríbeme «publica ya».")
    ya = orden == "ya" or sale <= ahora + timedelta(minutes=10)
    for p in piezas:
        p["en_programadas"] = ya

    def cambio():
        guardar(ruta("montados"), [x for x in cargar(ruta("montados"), []) if x["id"] != mont["id"]])
        corte = (ahora - timedelta(days=2)).strftime("%Y-%m-%d")
        ids = {x["id"] for x in piezas}
        guardar(ruta("listas"), [p for p in cargar(ruta("listas"), []) if p["fecha"] >= corte and p["id"] not in ids] + piezas)
        if ya:
            a_programadas([{k: v for k, v in p.items() if k != "en_programadas"} for p in piezas], ahora)

    aviso = (f"Listo, mandé a publicar <b>{mont['nombre']}</b> ya; sus historias salen detrás, cada 5 minutos. "
             "En unos minutos lo ves en tu perfil." if orden == "ya" else
             f"Listo: <b>{mont['nombre']}</b> sale {cuando_texto(sale, ahora)}, con sus historias detrás.")
    return cambio, aviso


def procesar(m, video):
    pend = elegir(cargar(ruta("pendientes"), []), m.get("caption") or "")
    if not pend:
        avisar("Recibí tu video, pero no hay ningún reel esperando una intro, así que no hice nada con él. "
               "Dime en el chat a qué reel va y lo dejo esperando.")
        return
    if (video.get("file_size") or 0) > LIMITE_TG:
        avisar("Tu video pesa más de 20 MB y el bot no lo puede bajar. Mándamelo como video normal "
               "(no como archivo) para que Telegram lo comprima, o grábalo un poco más corto.")
        return
    orden = orden_de(m.get("caption"))
    avisar(f"Recibí tu intro para <b>{pend['nombre']}</b>. La estoy editando y pegando al reel; en unos minutos te aviso.")
    trabajo = TMP / f"m{m['message_id']}"
    trabajo.mkdir(parents=True, exist_ok=True)
    ruta_tg = tg("getFile", {"file_id": video["file_id"]})["result"]["file_path"]
    intro = descargar(f"https://api.telegram.org/file/bot{TOKEN}/{ruta_tg}", trabajo / ("intro" + Path(ruta_tg).suffix))
    base = descargar(pend["base"], trabajo / "base.mp4")
    salida, info = montar(intro, base, pend, trabajo)
    huella = hashlib.sha1(salida.read_bytes()).hexdigest()[:10]
    nombre = f"{pend['id']}-intro-{huella}.mp4"
    url = BASE + nombre
    ahora = datetime.now(BOG)
    piezas = json.loads(json.dumps(pend["piezas"]))
    piezas[0]["archivos"] = [url]
    mont = {"id": pend["id"], "nombre": pend["nombre"], "archivo": url, "piezas": piezas,
            "montado": ahora.strftime("%Y-%m-%d %H:%M")}
    cambio_orden, aviso_orden = dar_orden(mont, orden, ahora) if orden else (None, None)

    def cambio():
        shutil.copy2(salida, REPO / nombre)
        guardar(ruta("pendientes"), [p for p in cargar(ruta("pendientes"), []) if p["id"] != pend["id"]])
        guardar(ruta("montados"), [x for x in cargar(ruta("montados"), []) if x["id"] != pend["id"]] + [mont])
        guardar(ruta("registro"), (cargar(ruta("registro"), []) + [{
            "fecha": ahora.strftime("%Y-%m-%d %H:%M"), "id": pend["id"], "archivo": nombre, "orden": orden,
            "original_s": info["original_s"], "intro_s": info["intro_s"], "total_s": info["total_s"],
            "texto": info["texto"], "mensaje": m["message_id"]}])[-50:])
        if cambio_orden:
            cambio_orden()

    aplicar(cambio, f"entrada: intro de {pend['id']}" + (f" ({orden})" if orden else ""))
    esperar_url(url, salida.stat().st_size)
    nota = " Ojo: pasa de 60 segundos." if info["total_s"] > 60 else ""
    hora_prog = datetime.fromisoformat(f"{pend['piezas'][0]['fecha']}T{pend['piezas'][0]['hora']}").replace(tzinfo=BOG)
    texto = (f"Quedó editado: <a href=\"{url}\">míralo aquí</a>. Tu parte pasó de {info['original_s']} s a "
             f"{info['intro_s']} s (le quité pausas y muletillas) y el reel completo dura {info['total_s']} s.{nota}\n\n"
             f"Lo que entendí: <i>{info['texto'][:300]}</i>\n\n")
    if aviso_orden:
        texto += aviso_orden
    else:
        texto += (f"No me dijiste cuándo publicarlo, así que queda esperando. Escríbeme «publica ya» o «publica en el "
                  f"horario programado» ({cuando_texto(hora_prog, ahora)}).")
    avisar(texto)


def orden_por_texto(texto):
    orden = orden_de(texto)
    if not orden:
        return False
    montados = cargar(ruta("montados"), [])
    if not montados:
        avisar("No tengo ningún video editado esperando orden. Mándame primero el video.")
        return True
    mont = elegir(montados[::-1], texto)  # el id si lo nombras; si no, el último que edité
    ahora = datetime.now(BOG)
    cambio, aviso = dar_orden(mont, orden, ahora)
    if cambio:
        aplicar(cambio, f"entrada: orden {orden} para {mont['id']}")
    avisar(aviso)
    return True


def despertar():
    """Cada corrida: si una pieza con orden de horario ya está en su hora, la pasa a programadas.json y empuja;
    el empujón dispara la rutina de la nube que publica."""
    ahora = datetime.now(BOG)
    vencen = []
    for p in cargar(ruta("listas"), []):
        if p.get("en_programadas") or p.get("despues_de"):
            continue
        sale = datetime.fromisoformat(f"{p['fecha']}T{p['hora']}").replace(tzinfo=BOG)
        if sale - timedelta(minutes=6) <= ahora <= sale + timedelta(minutes=90):
            vencen.append(p["id"])
    if not vencen:
        return

    def cambio():
        listas = cargar(ruta("listas"), [])
        salen = [p for p in listas if p["id"] in vencen or p.get("despues_de") in vencen]
        for p in salen:
            p["en_programadas"] = True
        guardar(ruta("listas"), listas)
        a_programadas([{k: v for k, v in p.items() if k != "en_programadas"} for p in salen], ahora)

    aplicar(cambio, "entrada: a su hora " + " ".join(vencen))
    avisar("Ya mandé a publicar " + ", ".join(f"<b>{i}</b>" for i in vencen) + " a su hora programada.")


def prueba():
    pendientes = cargar(ruta("pendientes"), [])
    pend = pendientes[0]
    TMP.mkdir(parents=True, exist_ok=True)
    base = descargar(pend["base"], TMP / "base.mp4")
    salida, info = montar(Path(PRUEBA), base, pend, TMP)
    print(json.dumps({k: v for k, v in info.items()}, ensure_ascii=False, indent=1))
    print("salida:", salida)


def main():
    if PRUEBA:
        return prueba()
    if not TOKEN or not CHAT:
        sys.exit("Faltan los secretos TELEGRAM_ENTRADA_TOKEN o TELEGRAM_CHAT_ID.")
    if "--despertar" in sys.argv:
        return despertar()
    r = tg("getUpdates", {"timeout": 0, "allowed_updates": json.dumps(["message"])})
    actualizaciones = r.get("result", [])
    if not actualizaciones:
        print("sin mensajes nuevos")
        return
    for u in actualizaciones:
        m = u.get("message") or {}
        if str(m.get("chat", {}).get("id")) != CHAT:
            continue  # solo se atiende el chat de Jonathan
        doc = m.get("document") or {}
        video = m.get("video") or (doc if str(doc.get("mime_type", "")).startswith("video/") else None)
        texto = (m.get("text") or "").strip()
        try:
            if video:
                procesar(m, video)
            elif orden_por_texto(texto):
                pass
            elif texto.lower() in ("/start", "estado", "pendientes"):
                pend = cargar(ruta("pendientes"), [])
                mont = cargar(ruta("montados"), [])
                avisar("Esperando tu video: " + (", ".join(f"<b>{p['nombre']}</b>" for p in pend) or "ninguno.")
                       + "\nEditados, esperando tu orden: " + (", ".join(f"<b>{p['nombre']}</b>" for p in mont) or "ninguno.")
                       + "\n\nCuando mandes un video, dime en el mismo mensaje «publica ya» o «publica en el horario programado».")
        except Exception as e:
            print("error:", limpio(e))
            avisar(f"No pude con tu mensaje: {limpio(e)[:300]}\n\nMándamelo otra vez; si falla de nuevo, lo reviso.")
    # confirma lo leído para no volver a procesarlo
    tg("getUpdates", {"offset": max(u["update_id"] for u in actualizaciones) + 1, "timeout": 0})


if __name__ == "__main__":
    main()
