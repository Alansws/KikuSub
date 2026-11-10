import { mount } from 'svelte';
import './app.css';
import App from './App.svelte';

// Svelte 5 用 mount()，不再是 new App()
mount(App, { target: document.getElementById('app')! });
