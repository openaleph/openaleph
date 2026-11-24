import { render, screen, waitFor, fireEvent, within } from 'testUtils';
import { endpoint } from 'app/api';
import ScopedTokens from './ScopedTokens';

jest.mock('app/api', () => ({
  endpoint: { get: jest.fn(), post: jest.fn(), delete: jest.fn() },
}));

const DAY = 24 * 60 * 60;
const SECRET = 'scoped.4.0123456789abcdef.s3cr3t';

const collections = [
  { id: '12', label: 'Panama Papers', writeable: false },
  { id: '15', label: 'My investigation', writeable: true, casefile: true },
];

const existing = {
  id: 'aaaaaaaaaaaaaaaa',
  label: 'Nightly import',
  read: [12, 15],
  write: [15],
  created_at: '2026-11-24T10:00:00+00:00',
  expires_at: '2099-01-01T00:00:00+00:00',
};

let tokens;

beforeEach(() => {
  tokens = [existing];
  endpoint.get.mockReset();
  endpoint.post.mockReset();
  endpoint.delete.mockReset();
  endpoint.get.mockImplementation((path) => {
    if (path === 'tokens') {
      return Promise.resolve({ data: { results: tokens } });
    }
    return Promise.resolve({ data: { results: collections } });
  });
});

const pickCollection = async (label) => {
  const input = screen.getByPlaceholderText('Search by name…');
  fireEvent.focus(input);
  fireEvent.click(await screen.findByText(label));
};

it('lists tokens without any secret', async () => {
  render(<ScopedTokens maxExpire={30 * DAY} />);
  expect(await screen.findByText('Nightly import')).toBeInTheDocument();
  expect(screen.getByText('2 collections, 1 writable')).toBeInTheDocument();
  expect(screen.queryByDisplayValue(SECRET)).not.toBeInTheDocument();
});

it('only offers lifetimes the instance allows', async () => {
  render(<ScopedTokens maxExpire={3 * DAY} />);
  await screen.findByText('Nightly import');
  const options = within(screen.getByLabelText('Expires after'))
    .getAllByRole('option')
    .map((option) => option.textContent);
  expect(options).toEqual(['1 hour', '1 day', '3 days']);
});

it('cannot create a token without a purpose and a collection', async () => {
  render(<ScopedTokens maxExpire={30 * DAY} />);
  await screen.findByText('Nightly import');
  const button = screen.getByRole('button', { name: /Create token/ });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText('What is this token for?'), {
    target: { value: 'Agent run' },
  });
  expect(button).toBeDisabled();
  await pickCollection('Panama Papers');
  expect(button).not.toBeDisabled();
});

it('creates a token, shows the secret once and resets the form', async () => {
  endpoint.post.mockImplementation((path, data) => {
    const token = { ...existing, id: 'bbbbbbbbbbbbbbbb', ...data };
    tokens = [existing, token];
    return Promise.resolve({ data: { ...token, token: SECRET } });
  });
  render(<ScopedTokens maxExpire={30 * DAY} />);
  await screen.findByText('Nightly import');

  fireEvent.change(screen.getByLabelText('What is this token for?'), {
    target: { value: ' Agent run ' },
  });
  await pickCollection('Panama Papers');
  await pickCollection('My investigation');

  // Write access can only be given where the user has it.
  const boxes = screen.getAllByLabelText('May write');
  expect(boxes[0]).toBeDisabled();
  expect(boxes[1]).not.toBeDisabled();
  fireEvent.click(boxes[1]);

  fireEvent.click(screen.getByRole('button', { name: /Create token/ }));
  await waitFor(() => expect(endpoint.post).toHaveBeenCalledTimes(1));
  expect(endpoint.post).toHaveBeenCalledWith('tokens', {
    label: 'Agent run',
    read: [12, 15],
    write: [15],
    expires_in: DAY,
  });

  expect(await screen.findByDisplayValue(SECRET)).toBeInTheDocument();
  expect(
    screen.getByText('Copy this token now. It will not be shown again.')
  ).toBeInTheDocument();
  expect(screen.getByLabelText('What is this token for?')).toHaveValue('');
  expect(screen.queryByLabelText('May write')).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'I have copied it' }));
  expect(screen.queryByDisplayValue(SECRET)).not.toBeInTheDocument();
});

it('revokes a token after confirmation', async () => {
  endpoint.delete.mockImplementation(() => {
    tokens = [];
    return Promise.resolve({ data: '' });
  });
  render(<ScopedTokens maxExpire={30 * DAY} />);
  await screen.findByText('Nightly import');

  fireEvent.click(screen.getByRole('button', { name: /Revoke/ }));
  expect(endpoint.delete).not.toHaveBeenCalled();
  const question = await screen.findByText(/Revoke the token/);
  const dialog = question.closest('.bp4-alert');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Revoke' }));

  await waitFor(() =>
    expect(endpoint.delete).toHaveBeenCalledWith('tokens/aaaaaaaaaaaaaaaa')
  );
  expect(
    await screen.findByText('You have no scoped tokens.')
  ).toBeInTheDocument();
});
