import { mount } from 'svelte';
import App from './App.svelte';
import './lib/styles/tokens.css';
import './lib/styles/components.css';
import './lib/styles/app.css';
import { app } from './lib/state/app.svelte';
import { voiceIO } from './lib/state/voice.svelte';

app.start();
void voiceIO.init();
mount(App, { target: document.getElementById('app')! });
