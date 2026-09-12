// Admin navigation links, rendered ONLY for a logged-in admin. It's a client
// island (not static HTML) so an anonymous visitor or a staff member never sees
// the admin page structure — a core rule: staff must not even know admin exists.
import { useEffect, useState } from 'preact/hooks';
import { getUser, groupsOf } from '../lib/auth';

const GROUPS: { title: string; links: [string, string][] }[] = [
  {
    title: 'Rozliczenia',
    links: [
      ['/panel', 'Rozliczenie'],
      ['/panel/dzien', 'Raport dzienny'],
      ['/panel/wizyty', 'Wizyty'],
      ['/panel/booksy', 'Booksy'],
      ['/panel/aliasy', 'Aliasy'],
    ],
  },
  {
    title: 'Zespół',
    links: [
      ['/panel/konta', 'Konta'],
      ['/panel/dokumenty', 'Dokumenty'],
      ['/panel/dyspozycyjnosc', 'Grafik'],
    ],
  },
  {
    title: 'Operacje',
    links: [['/panel/zaopatrzenie', 'Zamówienia']],
  },
];

export default function PanelNavLinks() {
  const [isAdmin, setIsAdmin] = useState(false);
  useEffect(() => {
    (async () => {
      const user = await getUser();
      if (user && !user.expired) setIsAdmin(groupsOf(user).includes('admin'));
    })();
  }, []);

  if (!isAdmin) return null;

  const path = window.location.pathname.replace(/\/$/, '') || '/panel';
  return (
    <nav class="pnav">
      {GROUPS.map((g) => (
        <div class="pnav-group" key={g.title}>
          <span class="pnav-title">{g.title}</span>
          <div class="pnav-links">
            {g.links.map(([href, label]) => (
              <a key={href} href={href} class={`pnav-link${path === href ? ' active' : ''}`}>
                {label}
              </a>
            ))}
          </div>
        </div>
      ))}
    </nav>
  );
}
