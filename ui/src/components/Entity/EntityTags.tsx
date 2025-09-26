import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Tag, Button, InputGroup } from '@blueprintjs/core';
import { Entity } from '@alephdata/followthemoney';
import { endpoint } from 'app/api';
import { showErrorToast, showSuccessToast } from 'app/toast';

import './EntityTags.scss';

interface IEntityTag {
  readonly id: string;
  readonly tag: string;
  readonly entity_id: string;
  readonly collection_id: number;
  readonly role_id: string;
  readonly created_at: string;
}

interface IEntityTagsProps {
  readonly entity: Entity;
}

const EntityTags: React.FC<IEntityTagsProps> = ({ entity }) => {
  const [tags, setTags] = useState<IEntityTag[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [deletingTags, setDeletingTags] = useState<Set<string>>(new Set());
  const [showInput, setShowInput] = useState<boolean>(false);
  const [newTagValue, setNewTagValue] = useState<string>('');
  const [creatingTag, setCreatingTag] = useState<boolean>(false);

  // Handle clicking outside input to close it
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (showInput && event.target instanceof Element) {
        const tagInput = event.target.closest('.EntityTags__input');
        const addButton = event.target.closest('.EntityTags__add-button');
        if (!tagInput && !addButton) {
          setShowInput(false);
          setNewTagValue('');
        }
      }
    };

    if (showInput) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showInput]);

  // Fetch tags for the entity
  const fetchTags = async () => {
    try {
      setLoading(true);
      const response = await endpoint.get(`tags/${entity.id}`);
      setTags(response.data.results || []);
    } catch (error) {
      showErrorToast('Failed to load tags');
      setTags([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (entity.id) {
      fetchTags();
    }
  }, [entity.id]);

  // Generate URL for tag search
  const getTagSearchUrl = (tagValue: string) => {
    return `/search?filter:tags=${encodeURIComponent(tagValue)}`;
  };

  const handleTagCreate = async (tagValue: string) => {
    if (!tagValue.trim() || tagValue.trim().length < 3) return;

    setCreatingTag(true);
    try {
      const payload = {
        entity_id: entity.id,
        tag: tagValue.trim(),
      };

      const response = await endpoint.post('tags', payload);

      // Add new tag to local state
      setTags((prevTags) => [...prevTags, response.data]);

      // Reset input
      setNewTagValue('');
      setShowInput(false);

      // Show success feedback
      showSuccessToast(`Added tag "${tagValue.trim()}"`);
    } catch (error) {
      showErrorToast('Failed to create tag');
    } finally {
      setCreatingTag(false);
    }
  };

  const handleTagDelete = async (tagValue: string) => {
    setDeletingTags((prev) => new Set(prev).add(tagValue));

    try {
      await endpoint.delete(
        `tags/${entity.id}/${encodeURIComponent(tagValue)}`
      );

      // Remove tag from local state
      setTags((prevTags) => prevTags.filter((tag) => tag.tag !== tagValue));

      // Show success feedback
      showSuccessToast(`Removed tag "${tagValue}"`);
    } catch (error) {
      showErrorToast('Failed to delete tag');
    } finally {
      setDeletingTags((prev) => {
        const newSet = new Set(prev);
        newSet.delete(tagValue);
        return newSet;
      });
    }
  };

  if (loading) {
    return (
      <div className="EntityTags">
        <div className="EntityTags__loading">
          <Tag icon="time" minimal>
            Loading tags...
          </Tag>
        </div>
      </div>
    );
  }

  const handleInputSubmit = () => {
    if (newTagValue.trim()) {
      handleTagCreate(newTagValue);
    }
  };

  const handleInputKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleInputSubmit();
    } else if (e.key === 'Escape') {
      setShowInput(false);
      setNewTagValue('');
    }
  };

  return (
    <div className="EntityTags">
      <div className="EntityTags__list">
        {tags.length ? 'Tags: ' : 'Add tag'}
        {tags.map((tag) => {
          const isDeleting = deletingTags.has(tag.tag);
          return (
            <div key={tag.id} className="EntityTags__tag-wrapper">
              <Link
                to={getTagSearchUrl(tag.tag)}
                className="EntityTags__tag-link"
                title={`Search for entities with tag "${tag.tag}"`}
              >
                <Tag
                  icon={isDeleting ? 'time' : 'tag'}
                  intent="primary"
                  minimal
                  className={`EntityTags__tag ${
                    isDeleting ? 'EntityTags__tag--deleting' : ''
                  }`}
                  title={tag.tag} // Show full tag text on hover
                  rightIcon={
                    !isDeleting ? (
                      <Button
                        icon="cross"
                        minimal
                        small
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          handleTagDelete(tag.tag);
                        }}
                        className="EntityTags__delete-button"
                        title={`Remove tag "${tag.tag}"`}
                      />
                    ) : undefined
                  }
                >
                  <span className="bp4-tag-text">{tag.tag}</span>
                </Tag>
              </Link>
            </div>
          );
        })}

        {showInput ? (
          <div className="EntityTags__input">
            <InputGroup
              placeholder="Add tag (min. 3 chars)..."
              value={newTagValue}
              onChange={(e) => setNewTagValue(e.target.value)}
              onKeyDown={handleInputKeyPress}
              rightElement={
                <Button
                  icon="tick"
                  minimal
                  intent="primary"
                  onClick={handleInputSubmit}
                  loading={creatingTag}
                  disabled={
                    !newTagValue.trim() ||
                    newTagValue.trim().length < 3 ||
                    creatingTag
                  }
                />
              }
              disabled={creatingTag}
              autoFocus
            />
          </div>
        ) : (
          <Button
            icon="plus"
            minimal
            intent="primary"
            onClick={() => setShowInput(true)}
            className="EntityTags__add-button"
            title="Add tag"
          />
        )}
      </div>
    </div>
  );
};

export default EntityTags;
