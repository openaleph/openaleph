import Query from 'app/Query';
import { render, screen } from 'testUtils';

import FacetedLayout from './FacetedLayout';

const makeLocation = () => ({
  pathname: '/search',
  search: '',
  hash: '',
});

const makeQuery = () => Query.fromLocation('entities', makeLocation(), {}, '');

const emptyResult = {
  total: 0,
  isPending: false,
  results: [],
  facets: {},
};

it('renders children and the facets sidebar', () => {
  render(
    <FacetedLayout
      query={makeQuery()}
      result={emptyResult}
      navigate={() => {}}
      location={makeLocation()}
      defaultFacets={['schema']}
      storageKey="test:faceted-layout"
    >
      <p>results body</p>
    </FacetedLayout>
  );

  // Children render inside the ContentPane.
  screen.getByText('results body');
  // The "Configure filters" trigger confirms the sidebar mounted.
  screen.getByText('Configure filters');
});

it('passes updateQuery to render-prop children', () => {
  let received;
  render(
    <FacetedLayout
      query={makeQuery()}
      result={emptyResult}
      navigate={() => {}}
      location={makeLocation()}
      defaultFacets={['schema']}
      storageKey="test:faceted-layout"
    >
      {({ updateQuery }) => {
        received = updateQuery;
        return <p>render-prop body</p>;
      }}
    </FacetedLayout>
  );

  screen.getByText('render-prop body');
  expect(typeof received).toBe('function');
});
