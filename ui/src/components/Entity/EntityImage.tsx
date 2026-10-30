import { Entity } from '@alephdata/followthemoney';
import { Spinner } from '@blueprintjs/core';
import { useEffect, useState } from 'react';
import Schema from 'react-ftm/types/Schema';

const DEFAULT_LANG = 'en';

interface IImageAttribution {
  readonly license: string;
  readonly license_url: string;
  readonly author?: string | null;
  readonly source?: string | null;
  readonly source_url?: string | null;
}

interface IImageAlt {
  readonly text: string;
  readonly language?: string;
}

interface IImageMeta {
  readonly id: string;
  readonly name: string;
  readonly sha256?: string | null;
  readonly url: string;
  readonly thumbnail_url: string;
  readonly original_url?: string | null;
  readonly alt: IImageAlt[];
  readonly attribution?: IImageAttribution | null;
}

interface IComponent {
  readonly entity: Entity;
  readonly root: string; // base url the asset store is served from
  readonly thumbnail?: boolean;
  readonly fallback?: boolean;
}

const extractAlt = (image: IImageMeta, lang: string = DEFAULT_LANG): string => {
  if (lang) {
    const alt =
      image.alt.find(({ language }) => language === lang) ||
      image.alt.find(({ language }) => language === DEFAULT_LANG);
    if (alt) return alt.text;
  }
  return image.alt[0]?.text || image.name;
};

const makeMetaUrl = (root: string, id: string): string =>
  `${root}/${id}/meta.json`;

// urls in meta.json are relative to its location
const resolveUrl = (url: string, base: string): string =>
  new URL(url, base).toString();

const getImage = async (
  root: string,
  id: string,
  opts: RequestInit = {}
): Promise<IImageMeta> => {
  const res = await fetch(makeMetaUrl(root, id), opts);
  if (!res.ok) {
    throw new Error(`Fetch error: ${res.status} ${res.statusText}`);
  }
  const image: IImageMeta = await res.json();
  return {
    ...image,
    url: resolveUrl(image.url, res.url),
    thumbnail_url: resolveUrl(image.thumbnail_url, res.url),
  };
};

export function ImageAttribution(props: { attribution: IImageAttribution }) {
  const { license, license_url, author, source, source_url } =
    props.attribution;
  return (
    <span className="ftm-assets__ImageAttribution">
      <span className="ftm-assets__ImageAttribution__license">
        License: <a href={license_url}>{license}</a>
      </span>
      {author ? (
        <span className="ftm-assets__ImageAttribution__author">
          Author: {author}
        </span>
      ) : null}
      {source ? (
        <span className="ftm-assets__ImageAttribution__source">
          {' / '}
          {source_url ? <a href={source_url}>{source}</a> : source}
        </span>
      ) : null}
    </span>
  );
}

export default function EntityImage(props: IComponent) {
  const [loading, setLoading] = useState<boolean>(false);
  const [image, setImage] = useState<IImageMeta | null>(null);
  const id = props.entity.getFirst('wikidataId');

  useEffect(() => {
    // currently, only qid is supported
    if (id) {
      setLoading(true);
      getImage(props.root, id.toString())
        .then((r) => {
          setImage(r);
          setLoading(false);
        })
        .catch(() => {
          setImage(null);
          setLoading(false);
        });
    } else {
      setLoading(false);
      setImage(null);
    }
  }, [id, props.root]);

  if (loading) {
    return (
      <span className="ftm-assets__Image-wrapper">
        <Spinner size={20} />
      </span>
    );
  }

  return image ? (
    <span className="ftm-assets__Image-wrapper">
      <img
        src={props.thumbnail ? image.thumbnail_url : image.url}
        alt={extractAlt(image)}
      />
      {image.attribution && (
        <ImageAttribution attribution={image.attribution} />
      )}
    </span>
  ) : props.fallback !== false ? (
    <span className="ftm-assets__Image-wrapper ftm-assets__Image-wrapper--fallback">
      <Schema.Icon schema={props.entity.schema} size={48} />
    </span>
  ) : null;
}
