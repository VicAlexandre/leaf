// leaf reader: foliate-js view with e-ink styling
import '../foliate/view.js'

const $ = s => document.querySelector(s)
const post = msg => window.webkit?.messageHandlers?.leaf?.postMessage(msg)

const state = await (await fetch('/state.json')).json()
const settings = state.settings
document.documentElement.dataset.theme = settings.theme

const SERIF = '"Bitstream Charter", "Charter", "Noto Serif", "DejaVu Serif", serif'
const bookCSS = () => {
    const ink = settings.theme === 'ink'
    const fg = ink ? '#E2E0D9' : '#1C1C1A', bg = ink ? '#1C1C1A' : '#EEEDE8'
    return `
    @namespace epub "http://www.idpf.org/2007/ops";
    html { color-scheme: ${ink ? 'dark' : 'light'}; font-size: ${settings.fontSize}px !important; }
    html, body { background: transparent !important; color: ${fg} !important; }
    body, p, li, blockquote, dd, dt, div, span, td, th, h1, h2, h3, h4, h5, h6, a, em, strong, i, b {
        font-family: ${SERIF} !important; color: ${fg} !important; background-color: transparent !important;
    }
    code, pre, kbd, samp, tt { font-family: "JetBrains Mono", monospace !important; color: ${fg} !important; }
    p, li, blockquote, dd { line-height: 1.55; hyphens: auto; -webkit-hyphens: auto; widows: 2; orphans: 2; }
    a:link, a:visited { color: ${fg} !important; text-decoration: underline; text-decoration-thickness: 1px; }
    hr { border: none; border-top: 1px solid ${fg}; }
    ::selection { background: ${fg}; color: ${bg}; }
    `
}

// ── open the book ────────────────────────────────────────────────────────────
const view = document.createElement('foliate-view')
$('#book').prepend(view)
const blob = await (await fetch('/book')).blob()
await view.open(new File([blob], state.book.name))
const { book } = view

const lang = x => !x ? '' : typeof x === 'string' ? x : x[navigator.language] ?? Object.values(x)[0] ?? ''
const people = x => [].concat(x ?? []).map(p => typeof p === 'string' ? p : lang(p?.name)).filter(Boolean).join(', ')
const title = lang(book.metadata?.title) || state.book.name.replace(/\.epub$/i, '')
const author = people(book.metadata?.author)
$('#title').textContent = title
$('#author').textContent = author
document.title = title

const r = view.renderer
r.setAttribute('flow', 'paginated')
r.setAttribute('margin', '36px')
r.setAttribute('gap', '7%')
r.setAttribute('max-inline-size', '680px')
// one page, or a two-page spread when the window is wide enough
const fitColumns = () => r.setAttribute('max-column-count', $('#book').clientWidth >= 1400 ? '2' : '1')
fitColumns()
new ResizeObserver(fitColumns).observe($('#book'))
r.removeAttribute('animated')                      // e-ink: pages change instantly
r.setStyles?.(bookCSS())

// ── progress ─────────────────────────────────────────────────────────────────
let saveTimer, currentHref = null, tocSel = 0
view.addEventListener('relocate', ({ detail }) => {
    const { fraction = 0, location, tocItem, cfi } = detail
    const pct = Math.round(fraction * 100)
    $('#progress').style.width = `${pct}%`
    $('#percent').textContent = `${pct}%`
    $('#loc').textContent = location ? `loc ${location.current + 1}/${location.total}` : ''
    $('#chapter').textContent = tocItem?.label ?? ''
    currentHref = tocItem?.href
    clearTimeout(saveTimer)
    saveTimer = setTimeout(() => post({ type: 'progress', cfi, fraction, title, author }), 400)
})
view.addEventListener('load', ({ detail: { doc } }) => doc.addEventListener('keydown', onKey))

await view.init({ lastLocation: state.book.cfi, showTextStart: !state.book.cfi })

// ── contents ─────────────────────────────────────────────────────────────────
const tocFlat = []
const walk = (items, depth) => { for (const it of items ?? []) { tocFlat.push({ ...it, depth }); walk(it.subitems, depth + 1) } }
walk(book.toc, 0)

const renderTOC = () => {
    const box = $('#toc-items')
    box.replaceChildren(...tocFlat.map((it, i) => {
        const d = document.createElement('div')
        d.className = `item${it.depth === 1 ? ' sub' : it.depth > 1 ? ' sub2' : ''}${i === tocSel ? ' sel' : ''}${it.href === currentHref ? ' current' : ''}`
        d.textContent = it.label?.trim() || '·'
        d.onclick = () => { tocSel = i; goToSel() }
        return d
    }))
    box.children[tocSel]?.scrollIntoView({ block: 'nearest' })
}
const tocOpen = () => !$('#toc').hidden
const toggleTOC = () => {
    const toc = $('#toc')
    toc.hidden = !toc.hidden
    if (!toc.hidden) {
        const cur = tocFlat.findIndex(it => it.href === currentHref)
        tocSel = cur >= 0 ? cur : 0
        renderTOC()
    }
}
const goToSel = () => {
    const it = tocFlat[tocSel]
    $('#toc').hidden = true
    if (it?.href) view.goTo(it.href)
}

// ── settings ─────────────────────────────────────────────────────────────────
const saveSettings = () => {
    document.documentElement.dataset.theme = settings.theme
    r.setStyles?.(bookCSS())
    post({ type: 'settings', settings })
}

// ── keys ─────────────────────────────────────────────────────────────────────
const turn = dir => { (dir > 0 ? view.next() : view.prev()); post({ type: 'turn' }) }
function onKey(e) {
    if (e.ctrlKey || e.altKey || e.metaKey) return
    const k = e.key
    if (tocOpen()) {
        if (k === 'ArrowDown' || k === 'j') tocSel = Math.min(tocFlat.length - 1, tocSel + 1)
        else if (k === 'ArrowUp' || k === 'k') tocSel = Math.max(0, tocSel - 1)
        else if (k === 'Enter') return goToSel()
        else if (k === 'Escape' || k === 't') return toggleTOC()
        else return
        e.preventDefault(); renderTOC(); return
    }
    if (['ArrowRight', 'l', ' ', 'PageDown', 'j', 'ArrowDown'].includes(k)) turn(+1)
    else if (['ArrowLeft', 'h', 'PageUp', 'k', 'ArrowUp', 'Backspace'].includes(k)) turn(-1)
    else if (k === 't') toggleTOC()
    else if (k === '+' || k === '=') { settings.fontSize = Math.min(34, settings.fontSize + 1); saveSettings() }
    else if (k === '-') { settings.fontSize = Math.max(12, settings.fontSize - 1); saveSettings() }
    else if (k === 'd') { settings.theme = settings.theme === 'ink' ? 'paper' : 'ink'; saveSettings() }
    else if (k === 's') { settings.pageSound = !settings.pageSound; saveSettings() }
    else if (k === 'b') post({ type: 'library' })
    else if (k === 'o') post({ type: 'open-dialog' })
    else if (k === 'q') post({ type: 'quit' })
    else if (k === 'Home') view.goToFraction(0)
    else if (k === 'End') view.goToFraction(1)
    else return
    e.preventDefault()
}
document.addEventListener('keydown', onKey)
document.addEventListener('wheel', e => { if (!tocOpen()) turn(e.deltaY > 0 ? 1 : -1) }, { passive: true })
