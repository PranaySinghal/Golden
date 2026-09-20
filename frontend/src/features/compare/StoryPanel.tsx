import type { Story } from '../../api/client'

interface StoryPanelProps {
  story: Story
  /** Takes the reader to the answer a figure came from. */
  onFollow: (questionId: string) => void
}

/**
 * The short version, over the cards. Every figure in it is a number the engine
 * computed, and clicking one goes to the answer it came from.
 */
export function StoryPanel({ story, onFollow }: StoryPanelProps) {
  const sentences = story.sentences ?? []
  if (sentences.length === 0) return null

  return (
    <section className="story" aria-labelledby="story-title">
      <h3 id="story-title" className="visually-hidden">
        What cleaning did
      </h3>
      <p className="story__text">
        {sentences.map((sentence, index) => (
          <span key={index} className="story__sentence">
            {(sentence.parts ?? []).map((part, position) =>
              part.question_id ? (
                <button
                  key={position}
                  type="button"
                  className="story__figure"
                  onClick={() => onFollow(part.question_id as string)}
                >
                  {part.text}
                </button>
              ) : (
                <span key={position}>{part.text}</span>
              ),
            )}{' '}
          </span>
        ))}
      </p>
    </section>
  )
}
