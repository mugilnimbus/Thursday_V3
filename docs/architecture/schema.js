// The shared vocabulary of the architecture model: the kinds of part and their shapes, the levels, the
// connection categories, the journey types, and the palettes. The viewer, the loader and the checker all
// read this file, so a list is changed in one place only. Projects edit model.js, never this file.
window.ARCH_SCHEMA = {
  // What a part is. Each kind has one shape and asks for its own fields (the checker enforces `needs`).
  kinds: {
    external: { label: 'External', shape: 'Rectangle with double sides', needs: [],
      hint: 'A person, a caller, or an outside service' },
    group: { label: 'Group', shape: 'Box with a title band', needs: ['children'],
      hint: 'A system, service, module or component that holds other parts' },
    step: { label: 'Step', shape: 'Rectangle', needs: ['in', 'out'],
      hint: 'Does one thing to the data: reads, changes, splits, sends' },
    decision: { label: 'Decision', shape: 'Diamond', needs: ['test', 'branches'],
      hint: 'Tests one condition and sends the data down one branch' },
    store: { label: 'Store', shape: 'Cylinder', needs: ['keeps'],
      hint: 'Keeps data: a database, a table, a file' },
    queue: { label: 'Queue', shape: 'Box with bars', needs: ['capacity', 'when_full'],
      hint: 'Holds items in order: a queue, a buffer, a batch' },
    event: { label: 'Event', shape: 'Pill with a dot', needs: ['trigger'],
      hint: 'Starts a journey: a click, a timer, a signal, data arriving' },
    ui: { label: 'UI', shape: 'Screen', needs: [],
      hint: 'What a person sees and does; its events start journeys' }
  },

  // What each level shows. Levels count from the whole system; level 4 and deeper are all "Detail".
  levels: ['System', 'Containers', 'Components', 'Detail'],

  // Where a top-level part sits: on the main line, or on one side of it.
  lanes: ['main', 'top', 'bottom', 'left', 'right'],

  statuses: { accepted: 'Accepted', open: 'Open', revisit: 'Needs revisit' },

  // What starts a journey. Every journey names one type.
  journeyTypes: {
    user: 'A person does something in the UI',
    call: 'An outside caller sends a request',
    timer: 'A timer or a schedule fires',
    signal: 'A limit, a failure, or a shutdown',
    data: 'Data arrives: a file, a message, a sensor reading'
  },

  // Every connection has exactly one category. The category sets the colour and the arrowhead.
  // Line style: dotted when the sender waits for an answer, solid when it hands off and does not wait (async).
  links: {
    data: { label: 'Data flow', hint: 'The thing being processed moves along it', head: 'filled',
      color: { dark: '#6ea8ff', light: '#1d4ed8' } },
    control: { label: 'Control flow', hint: 'A signal that makes the receiver do something: start, stop, pause, retry', head: 'filled',
      color: { dark: '#b79bff', light: '#6d28d9' } },
    result: { label: 'Result', hint: 'The answer on its way back', head: 'open',
      color: { dark: '#4fd1a5', light: '#047857' } },
    error: { label: 'Error or refusal', hint: 'What happens when it does not go through', head: 'bar',
      color: { dark: '#ff7a6b', light: '#b91c1c' } },
    store: { label: 'Storage', hint: 'Written to or read from something that persists', head: 'filled',
      color: { dark: '#f08fd0', light: '#a21caf' } },
    monitor: { label: 'Monitoring', hint: 'Metrics and logs', head: 'dot',
      color: { dark: '#8f94a8', light: '#5b6472' } },
    ui: { label: 'Shown in the UI', hint: 'Data a person sees', head: 'filled',
      color: { dark: '#8fe07a', light: '#15803d' } },
    config: { label: 'Configuration', hint: 'A setting a person can change', head: 'filled',
      color: { dark: '#f2d04a', light: '#a16207' } }
  },

  // Categories that set the left-to-right order of the main line.
  forward: ['data', 'control', 'store'],
  // The front-end contract: lines into and out of the UI. The viewer can hide them for a moment.
  contract: ['ui', 'config'],
  // Lines that need no contract card: docs/API.md and /metrics already describe them.
  noCardNeeded: ['ui', 'config', 'monitor'],
  // Lines that need not be on a journey: monitoring runs all the time.
  offJourney: ['monitor'],

  // The pack's six palettes (design-system tokens.css), reduced to what a diagram needs.
  // model.js picks one with `palette: '...'`; the default is violet.
  palettes: {
    violet: {
      dark: { bg: '#0c0b10', surface: '#141219', raised: '#1d1a24', border: '#2e2938', text: '#f5f3f8', muted: '#a39dab', accent: '#a78bfa', warn: '#e0a53a' },
      light: { bg: '#f8f7fa', surface: '#ffffff', raised: '#f1eff5', border: '#ded9e5', text: '#18161d', muted: '#716b7a', accent: '#7c3aed', warn: '#9a6700' }
    },
    graphite: {
      dark: { bg: '#0b0d10', surface: '#12151a', raised: '#191d24', border: '#272d36', text: '#f4f6f8', muted: '#9aa3af', accent: '#60a5fa', warn: '#e0a53a' },
      light: { bg: '#f7f8fa', surface: '#ffffff', raised: '#f0f2f5', border: '#dde1e7', text: '#111318', muted: '#666e7a', accent: '#0b5fe9', warn: '#9a6700' }
    },
    slate: {
      dark: { bg: '#080c0f', surface: '#10161b', raised: '#172027', border: '#23333b', text: '#ecf7fa', muted: '#8fa6af', accent: '#22d3ee', warn: '#e0a53a' },
      light: { bg: '#f5f7f8', surface: '#ffffff', raised: '#edf2f4', border: '#d5e0e4', text: '#1b2a30', muted: '#616f75', accent: '#07718b', warn: '#9a6700' }
    },
    stone: {
      dark: { bg: '#0d0f0e', surface: '#151816', raised: '#1c211e', border: '#29312c', text: '#f2f5f3', muted: '#96a19a', accent: '#34d399', warn: '#e0a53a' },
      light: { bg: '#f6f6f3', surface: '#ffffff', raised: '#eeeeea', border: '#d9ddd9', text: '#1c201e', muted: '#666d67', accent: '#047351', warn: '#9a6700' }
    },
    amber: {
      dark: { bg: '#0f0e0c', surface: '#181613', raised: '#211e19', border: '#312c24', text: '#f6f3ec', muted: '#a69e90', accent: '#f59e0b', warn: '#e0a53a' },
      light: { bg: '#f7f6f2', surface: '#ffffff', raised: '#efede7', border: '#ddd8cd', text: '#1b1915', muted: '#706a5f', accent: '#9d5705', warn: '#9a6700' }
    },
    lime: {
      dark: { bg: '#090a09', surface: '#111311', raised: '#191c19', border: '#2a302a', text: '#f4f7f4', muted: '#949894', accent: '#a3e635', warn: '#e0a53a' },
      light: { bg: '#fafafa', surface: '#ffffff', raised: '#f1f2f1', border: '#dee1de', text: '#151715', muted: '#6b706b', accent: '#487409', warn: '#9a6700' }
    }
  }
};
