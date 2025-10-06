# Gunicorn

<div class="hero">
  <div class="hero__inner">
    <div class="hero__copy">
      <img class="hero__logo" src="assets/gunicorn.svg" alt="Gunicorn mascot" />
      <h1>Production-ready Python web services</h1>
      <p>Gunicorn is a dependable WSGI HTTP server for UNIX that keeps Python applications running fast and resilient in production. Built on a pre-fork worker model and trusted in countless deployments, it pairs clean configuration with flexible worker strategies so you can meet any traffic pattern.</p>
      <div class="hero__cta">
        <a class="md-button md-button--primary" href="install/">Install Gunicorn</a>
        <a class="md-button" href="https://github.com/benoitc/gunicorn">View on GitHub</a>
      </div>
    </div>
    <div class="hero__code">
      <pre><code class="language-console">$ pip install gunicorn
$ gunicorn example:app --workers 3</code></pre>
      <div class="hero__version">Latest release: <span>{{ release }}</span></div>
    </div>
  </div>
</div>

## Quickstart

1. Install Gunicorn into your application environment.
2. Point Gunicorn at your WSGI app: `gunicorn myproject.wsgi`.
3. Tune worker type, concurrency, and hooks using the rich [settings](reference/settings.md).

Need a longer walkthrough? Jump into the [install guide](install.md).

## Why teams choose Gunicorn

<section class="feature-grid">
  <article class="feature-card">
    <h3>Works with your framework</h3>
    <p>Django, Flask, FastAPI, Pyramid, you name it&mdash;Gunicorn speaks WSGI so your stack just runs.</p>
    <a href="run/">Running Gunicorn &rarr;</a>
  </article>
  <article class="feature-card">
    <h3>Flexible workers</h3>
    <p>Sync, async, gevent, eventlet&mdash;choose the concurrency model that fits.</p>
    <a href="reference/settings/#worker_class">Worker classes &rarr;</a>
  </article>
  <article class="feature-card">
    <h3>Battle-tested hooks</h3>
    <p>Lifecycle hooks let you instrument, reload, and extend Gunicorn to match your deployment requirements.</p>
    <a href="custom/">Server hooks &rarr;</a>
  </article>
  <article class="feature-card">
    <h3>Containers to bare metal</h3>
    <p>Deploy with systemd, Kubernetes, Heroku, or Docker&mdash;the configuration stays predictable everywhere.</p>
    <a href="deploy/">Deployment patterns &rarr;</a>
  </article>
</section>

## Documentation map

- [Install](install.md): Set up Gunicorn in a clean environment.
- [Run](run.md): CLI usage and integration with frameworks.
- [Configure](configure.md): Combine CLI flags and config files effectively.
- [Settings reference](reference/settings.md): Generated from the Gunicorn source of truth.
- [Signals](signals.md): Manage worker lifecycle in production.
- [Instrumentation](instrumentation.md): Monitor metrics and logs.

## Community & support

- Report bugs or request features on [GitHub Issues](https://github.com/benoitc/gunicorn/issues).
- Discuss strategies with maintainers in `#gunicorn` on [Libera Chat](https://libera.chat/).
- Contributions are welcome&mdash;see the [contributing guide](community.md#contributing) and say hi to the maintainers.
