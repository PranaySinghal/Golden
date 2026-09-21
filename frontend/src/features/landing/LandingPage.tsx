import { useQuery } from '@tanstack/react-query'

import { api, type DatasetSummary } from '../../api/client'
import { Faq } from './Faq'
import { FeatureCards } from './FeatureCards'
import { Hero } from './Hero'
import { StatsRow } from './StatsRow'

interface LandingPageProps {
  onUploaded: (dataset: DatasetSummary) => void
}

export function LandingPage({ onUploaded }: LandingPageProps) {
  // The upload panel asks for this too; the query cache makes that one request.
  const limits = useQuery({ queryKey: ['upload-limits'], queryFn: api.getUploadLimits })

  return (
    <div className="landing">
      <Hero onUploaded={onUploaded} />
      <StatsRow />
      <FeatureCards />
      <Faq maxBytes={limits.data?.max_upload_bytes ?? null} />
    </div>
  )
}
