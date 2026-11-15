import { render, screen } from 'testUtils';

import PreviewHotkeys from './PreviewHotkeys';

it('renders its children', () => {
  const result = { results: [] };
  render(
    <PreviewHotkeys result={result} groupLabel="Test">
      <p>body</p>
    </PreviewHotkeys>
  );
  screen.getByText('body');
});

it('tolerates an undefined result', () => {
  // A mode that hasn't loaded yet shouldn't crash.
  render(
    <PreviewHotkeys result={undefined} groupLabel="Test">
      <p>nothing loaded</p>
    </PreviewHotkeys>
  );
  screen.getByText('nothing loaded');
});
