import { auth } from '@/auth'
import { GamesListClient } from '@/components/games-list-client'

export default async function GamesPage() {
  const session = await auth()
  const userIdentityId = session?.user?.id ?? null
  return <GamesListClient userIdentityId={userIdentityId} />
}
