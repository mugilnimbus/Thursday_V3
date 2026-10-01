/* The current route, kept in the URL hash so reload, back, and deep links work. */

import { parseRoute, routeHref, sectionOf, type Route } from './routes';

class Router {
  route = $state<Route>(parseRoute(location.hash));
  section = $derived(sectionOf(this.route));

  constructor() {
    window.addEventListener('hashchange', () => (this.route = parseRoute(location.hash)));
  }

  go(route: Route, replace = false): void {
    const href = routeHref(route);
    if (replace) history.replaceState(null, '', href);
    else if (location.hash !== href) history.pushState(null, '', href);
    this.route = route;
  }
}

export const router = new Router();
