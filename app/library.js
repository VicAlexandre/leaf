// leaf library: recent books, keyboard driven
const $ = s => document.querySelector(s)
const post = msg => window.webkit?.messageHandlers?.leaf?.postMessage(msg)

const state = await (await fetch('/state.json')).json()
const settings = state.settings
document.documentElement.dataset.theme = settings.theme
const books = state.recent
let sel = 0

const render = () => {
    const box = $('#books')
    if (!books.length) {
        box.innerHTML = '<p class="empty">No books yet. Press <kbd>o</kbd> to open an EPUB.</p>'
        return
    }
    box.replaceChildren(...books.map((b, i) => {
        const row = document.createElement('div')
        row.className = `book${i === sel ? ' sel' : ''}`
        const text = document.createElement('div')
        const t = document.createElement('div'); t.className = 't'; t.textContent = b.title
        const a = document.createElement('div'); a.className = 'a'
        a.textContent = [b.author, `${Math.round((b.fraction || 0) * 100)}%`].filter(Boolean).join(' · ')
        text.append(t, a)
        const bar = document.createElement('div'); bar.className = 'bar'
        const fill = document.createElement('i'); fill.style.width = `${Math.round((b.fraction || 0) * 100)}%`
        bar.append(fill)
        row.append(text, bar)
        row.onclick = () => post({ type: 'open', path: b.path })
        return row
    }))
    box.children[sel]?.scrollIntoView({ block: 'nearest' })
}

document.addEventListener('keydown', e => {
    const k = e.key
    if ((k === 'ArrowDown' || k === 'j') && books.length) sel = (sel + 1) % books.length
    else if ((k === 'ArrowUp' || k === 'k') && books.length) sel = (sel - 1 + books.length) % books.length
    else if (k === 'Enter' && books[sel]) return post({ type: 'open', path: books[sel].path })
    else if (k === 'o') return post({ type: 'open-dialog' })
    else if (k === 'd') {
        settings.theme = settings.theme === 'ink' ? 'paper' : 'ink'
        document.documentElement.dataset.theme = settings.theme
        post({ type: 'settings', settings })
    }
    else if (k === 'q') return post({ type: 'quit' })
    else return
    e.preventDefault()
    render()
})
render()
