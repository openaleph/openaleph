import { render, screen } from 'testUtils';
import { Entity, Model, defaultModel } from '@alephdata/followthemoney';

import EmailPropertyValues from './EmailPropertyValues';

const model = new Model(defaultModel);

it('renders default property values if no entity property is given', () => {
  const entity = new Entity(model, {
    id: '123',
    schema: 'Email',
    properties: {
      from: ['john.doe@example.org'],
    },
  });

  render(<EmailPropertyValues entity={entity} prop="from" />);

  screen.getByText('john.doe@example.org');
});

it('merges values from entity property and default property by email address', () => {
  const entity = new Entity(model, {
    id: '123',
    schema: 'Email',
    properties: {
      to: ['John.Doe@example.org', 'Jane Doe <Jane.Doe@example.org>'],
      recipients: [
        {
          id: '456',
          schema: 'Person',
          properties: {
            name: ['Jane Doe'],
            email: ['Jane.Doe@example.org'],
          },
        }
      ],
    }
  });

  render(<EmailPropertyValues entity={entity} prop="to" />);

  expect(screen.getAllByText(/John.Doe@example.org/)).toHaveLength(1);
  screen.getByText(/John.Doe@example.org/);

  expect(screen.getAllByText(/Jane.Doe@example.org/)).toHaveLength(1);
  screen.getByRole('link', { name: /Jane Doe <Jane.Doe@example.org>/ });

  expect(document.body.textContent).toEqual(
    'John.Doe@example.org · Jane Doe <Jane.Doe@example.org>'
  );
});
