import { Icon, Tag } from '@blueprintjs/core';
import convertHighlightsToReactElements from 'util/convertHighlightsToReactElements';
import './SearchHighlight.scss';

const hasRealHighlight = (arr) => arr?.some((s) => /<em>/i.test(s));

const NamesHighlight = ({ names }) => (
  <span className="SearchHighlight__names">
    {names.map((n, i) => (
      <Tag key={`${n}-${i}`} minimal round>
        {n}
      </Tag>
    ))}
  </span>
);

const TextHighlight = ({ texts }) => (
  <span className="SearchHighligh__fragment">
    {texts.map(convertHighlightsToReactElements)}
  </span>
);

export default function SearchHighlight({ highlight }) {
  if (!highlight || Object.keys(highlight).length <= 0) {
    return null;
  }

  if (!!highlight.content || !!highlight.name || !!highlight.names) {
    delete highlight['text'];
  }
  if (!!highlight.name) {
    delete highlight['names'];
  }

  let showTranslation = false;
  if (highlight.translation && hasRealHighlight(highlight.translation)) {
    if (!hasRealHighlight(highlight.content)) {
      delete highlight['content'];
      delete highlight['text'];
    }
    showTranslation = true;
  }

  return (
    <p className="SearchHighlight">
      {highlight.name && <NamesHighlight names={highlight.name} />}
      {highlight.names && <NamesHighlight names={highlight.names} />}
      {highlight.content && <TextHighlight texts={highlight.content} />}
      {highlight.text && <TextHighlight texts={highlight.text} />}
      {showTranslation && (
        <span className="SearchHighlight__translation">
          <span className="SearchHighlight__translation-badge">
            <Icon icon="translate" size={12} />
            translated
          </span>
          <TextHighlight texts={highlight.translation} />
        </span>
      )}
    </p>
  );
}
