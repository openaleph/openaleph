import getCanonicalLink from './getCanonicalLink';

export default function getEntityLink(entity, profile = true) {
  if (profile && entity?.canonicalId) {
    return getCanonicalLink(entity.canonicalId, { via: entity.id });
  }
  const entityId = typeof entity === 'string' ? entity : entity?.id;
  const fragment = !profile ? '#profile=false' : '';
  return entityId ? `/entities/${entityId}${fragment}` : null;
}
