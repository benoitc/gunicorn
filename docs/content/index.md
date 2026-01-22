# Gunicorn

<div class="hero">
  <div class="hero__inner">
    <div class="hero__copy">
      <img class="hero__logo" src="assets/gunicorn.svg" alt="Gunicorn mascot" />
      <h1>The Python WSGI Server<br>for Production</h1>
      <p class="hero__tagline">Fast, reliable, and battle-tested. Gunicorn runs your Python web applications with the stability and performance you need in production.</p>
      <div class="hero__cta">
        <a class="md-button md-button--primary" href="quickstart/">Get Started</a>
        <a class="md-button" href="https://github.com/benoitc/gunicorn">GitHub</a>
      </div>
    </div>
    <div class="hero__code">
      <pre><code class="language-bash">pip install gunicorn
gunicorn myapp:app --workers 4</code></pre>
      <div class="hero__version">v{{ release }}</div>
    </div>
  </div>
</div>

<section class="pillars">
  <div class="pillar">
    <div class="pillar__icon">🚀</div>
    <h3>Production-Proven</h3>
    <p>Trusted by thousands of companies worldwide. The pre-fork worker model handles traffic spikes gracefully.</p>
  </div>
  <div class="pillar">
    <div class="pillar__icon">⚡</div>
    <h3>Lightweight</h3>
    <p>Minimal dependencies, simple configuration. Runs efficiently from containers to bare metal servers.</p>
  </div>
  <div class="pillar">
    <div class="pillar__icon">🔌</div>
    <h3>Compatible</h3>
    <p>Works with any WSGI framework. Django, Flask, Pyramid—your app just runs. Now with ASGI support.</p>
  </div>
</section>

## Works With Your Stack

<div class="frameworks">
  <div class="framework" title="Django">
    <span class="framework__name">Django</span>
  </div>
  <div class="framework" title="Flask">
    <span class="framework__name">Flask</span>
  </div>
  <div class="framework" title="FastAPI">
    <span class="framework__name">FastAPI</span>
  </div>
  <div class="framework" title="Pyramid">
    <span class="framework__name">Pyramid</span>
  </div>
  <div class="framework" title="Starlette">
    <span class="framework__name">Starlette</span>
  </div>
  <div class="framework" title="Falcon">
    <span class="framework__name">Falcon</span>
  </div>
</div>

## Choose Your Worker

<section class="feature-grid">
  <article class="feature-card">
    <h3>Sync Workers</h3>
    <p>The default. One request per worker. Simple, predictable, and perfect for most applications.</p>
    <a href="design/#sync-workers">Learn more</a>
  </article>
  <article class="feature-card">
    <h3>Async Workers</h3>
    <p>Gevent or Eventlet for thousands of concurrent connections. Ideal for I/O-bound workloads.</p>
    <a href="design/#async-workers">Learn more</a>
  </article>
  <article class="feature-card">
    <h3>Thread Workers</h3>
    <p>Multiple threads per worker. Balance between concurrency and simplicity.</p>
    <a href="reference/settings/#threads">Learn more</a>
  </article>
  <article class="feature-card">
    <h3>ASGI Workers <span class="badge badge--new">Beta</span></h3>
    <p>Native asyncio support for FastAPI, Starlette, and other async frameworks.</p>
    <a href="asgi/">Learn more</a>
  </article>
</section>

## Quick Links

<div class="quick-links">
  <a href="quickstart/" class="quick-link">
    <strong>Quickstart</strong>
    <span>Get running in 5 minutes</span>
  </a>
  <a href="deploy/" class="quick-link">
    <strong>Deployment</strong>
    <span>Nginx, systemd, Docker</span>
  </a>
  <a href="reference/settings/" class="quick-link">
    <strong>Settings</strong>
    <span>100+ configuration options</span>
  </a>
  <a href="faq/" class="quick-link">
    <strong>FAQ</strong>
    <span>Common questions answered</span>
  </a>
</div>

## Community

<div class="community-links">

- **[GitHub Issues](https://github.com/benoitc/gunicorn/issues)** — Report bugs and request features
- **[#gunicorn on Libera Chat](https://web.libera.chat/#gunicorn)** — Chat with the community
- **[Contributing](community/#contributing)** — Help improve Gunicorn

</div>
