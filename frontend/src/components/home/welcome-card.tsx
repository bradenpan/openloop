import { Card, CardBody, Button } from '../ui';

interface WelcomeCardProps {
  onCreateSpace: () => void;
}

export function WelcomeCard({ onCreateSpace }: WelcomeCardProps) {
  return (
    <Card className="border-primary/30">
      <CardBody className="flex flex-col items-center text-center py-12 px-6 gap-4">
        <h2 className="text-xl font-bold text-foreground">Welcome to OpenLoop</h2>
        <p className="text-sm text-muted max-w-md">
          Your AI command center. Create a space to start organizing projects, tracking tasks, and
          running agent conversations.
        </p>
        <Button onClick={onCreateSpace} size="lg">
          Create your first space
        </Button>
      </CardBody>
    </Card>
  );
}
