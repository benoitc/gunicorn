---
template: home.html
title: Gunicorn - Python WSGI HTTP Server
---

<section class="hero">
  <div class="container">
    <img class="hero__logo" src="assets/gunicorn.svg" alt="Gunicorn" style="width: 350px;" />
    <h1>Serve Python on the Web</h1>
    <p class="hero__tagline">
      Battle-tested. Production-ready. One command to serve your Python apps.
    </p>
    <div class="hero__buttons">
      <a class="btn btn--primary" href="quickstart/">Get Started</a>
      <a class="btn btn--secondary" href="https://github.com/benoitc/gunicorn">View on GitHub</a>
    </div>
    <div class="terminal">
      <div class="terminal__header">
        <span class="terminal__dot terminal__dot--red"></span>
        <span class="terminal__dot terminal__dot--yellow"></span>
        <span class="terminal__dot terminal__dot--green"></span>
      </div>
      <div class="terminal__body">
        <span class="terminal__line"><span class="terminal__prompt">$ </span>pip install gunicorn</span>
        <span class="terminal__line"><span class="terminal__prompt">$ </span>gunicorn myapp:app</span>
        <span class="terminal__line terminal__comment"># Listening at http://127.0.0.1:8000</span>
      </div>
    </div>
  </div>
</section>

<section class="why">
  <div class="container">
    <h2>Why Gunicorn?</h2>
    <div class="pillars">
      <div class="pillar">
        <h3>Production-Proven</h3>
        <p>Trusted by thousands of companies. The pre-fork worker model handles traffic spikes gracefully.</p>
      </div>
      <div class="pillar">
        <h3>Lightweight</h3>
        <p>Minimal dependencies, simple configuration. Efficient from containers to bare metal.</p>
      </div>
      <div class="pillar">
        <h3>Compatible</h3>
        <p>Works with any WSGI or ASGI framework. Django, Flask, FastAPI—it just runs.</p>
      </div>
    </div>
  </div>
</section>

<section class="frameworks">
  <div class="container">
    <h2>Works With Your Stack</h2>
    <p class="frameworks__subtitle">WSGI and ASGI frameworks, no changes needed</p>
    <div class="frameworks__list">
      <span class="framework-tag">Django</span>
      <span class="framework-tag">Flask</span>
      <span class="framework-tag framework-tag--new">FastAPI</span>
      <span class="framework-tag">Pyramid</span>
      <span class="framework-tag framework-tag--new">Starlette</span>
      <span class="framework-tag">Falcon</span>
      <span class="framework-tag">Bottle</span>
      <span class="framework-tag framework-tag--new">Quart</span>
    </div>
  </div>
</section>

<section class="workers">
  <div class="container">
    <h2>Choose Your Worker</h2>
    <div class="workers__grid">
      <a class="worker" href="design/#sync-workers">
        <h3>Sync</h3>
        <p>The default. One request per worker. Simple and predictable.</p>
      </a>
      <a class="worker" href="design/#async-workers">
        <h3>Async (Gevent/Eventlet)</h3>
        <p>Thousands of concurrent connections for I/O-bound workloads.</p>
      </a>
      <a class="worker" href="reference/settings/#threads">
        <h3>Threads</h3>
        <p>Multiple threads per worker. Balance concurrency and simplicity.</p>
      </a>
      <a class="worker" href="asgi/">
        <h3>ASGI <span class="badge">Beta</span></h3>
        <p>Native asyncio for FastAPI, Starlette, and async frameworks.</p>
      </a>
    </div>
  </div>
</section>

<section class="quick-links">
  <div class="container">
    <h2>Documentation</h2>
    <div class="quick-links__grid">
      <a class="quick-link" href="quickstart/">
        <strong>Quickstart</strong>
        <span>Get running in 5 minutes</span>
      </a>
      <a class="quick-link" href="deploy/">
        <strong>Deployment</strong>
        <span>Nginx, systemd, Docker</span>
      </a>
      <a class="quick-link" href="reference/settings/">
        <strong>Settings</strong>
        <span>All configuration options</span>
      </a>
      <a class="quick-link" href="faq/">
        <strong>FAQ</strong>
        <span>Common questions</span>
      </a>
    </div>
  </div>
</section>

<section class="sponsors">
  <div class="container">
    <h2>Support</h2>
    <p>gunicorn has been serving Python web applications since 2010. If it's running in your production stack and saving your team time and money, please consider supporting its continued development.</p>
    <p>Your sponsorship helps cover security updates, compatibility with new Python versions, bug fixes, and documentation maintenance.</p>
    <p><strong>Corporate sponsors:</strong> If gunicorn is part of your infrastructure, <a href="mailto:benoitc@enki-multimedia.eu">reach out</a> for sponsored support options.</p>
    <a class="btn btn--secondary" href="https://github.com/sponsors/benoitc">Become a Sponsor</a>
  </div>
</section>

<section class="home-footer">
  <div class="container">
    <h2>Join the Community</h2>
    <p>Questions? Bugs? Ideas? We're here to help.</p>
    <div class="home-footer__links">
      <a href="https://github.com/benoitc/gunicorn/issues">GitHub Issues</a>
      <a href="https://web.libera.chat/#gunicorn">#gunicorn on Libera</a>
      <a href="community/">Contributing</a>
    </div>
  </div>
</section>
