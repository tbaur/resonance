import { useEffect, useState } from 'react';
import { api } from '@/api/client';

const WEB_ADDRESS = /^https?:\/\//i;

/** A pill that opens Valence. It shows only when the server has Valence's address. */
export function ValenceLink() {
  const [url, setUrl] = useState('');

  useEffect(() => {
    api
      .links()
      .then((links) => setUrl(links.valence_url))
      .catch(() => setUrl(''));
  }, []);

  if (!WEB_ADDRESS.test(url)) return null;
  return (
    <a className="pill pill-link" href={url} target="_blank" rel="noopener noreferrer">
      Valence
    </a>
  );
}
